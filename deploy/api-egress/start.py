"""Trusted sidecars only. Their environment never contains API credentials."""
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def hostname(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value):
        raise ValueError("expected an exact lowercase hostname")
    if len(value) > 253 or all(c.isdigit() or c == '.' for c in value):
        raise ValueError("IP literals are forbidden")
    return value


def squid_config(mode: str, supabase_host: str) -> str:
    if mode not in {"audit", "enforce"}:
        raise ValueError("EGRESS_MODE must be audit or enforce")
    hosts = [hostname(line.strip()) for line in (ROOT / 'hosts.txt').read_text().splitlines()
             if line.strip() and not line.startswith('#')]
    hosts.append(hostname(supabase_host))
    names = ' '.join(sorted(set(hosts)))
    # Check names before any DNS-dependent ACL, including the private-IP check.
    enforcement = 'http_access deny !approved' if mode == 'enforce' else ''
    reject = 'ssl_bump terminate !approved' if mode == 'enforce' else ''
    splice = 'ssl_bump splice tls_approved' if mode == 'enforce' else 'ssl_bump splice all'
    return f"""http_port 3128 ssl-bump cert=/tmp/proxy.pem generate-host-certificates=off
visible_hostname api-egress
pinger_enable off
pid_filename /tmp/squid.pid
cache deny all
cache_store_log none
cache_log /dev/stderr
logfile_rotate 0
logformat listed mode={mode} policy=allowlisted %ts.%03tu %>a %rm %ru %Ss/%>Hs sni=%ssl::>sni
logformat unlisted mode={mode} policy=unlisted %ts.%03tu %>a %rm %ru %Ss/%>Hs sni=%ssl::>sni
acl api src 172.30.87.2/32
acl connect method CONNECT
acl tls_port port 443
acl approved dstdomain -n {names}
acl tls_approved ssl::server_name --client-requested {names}
acl inventoried all-of approved tls_approved
access_log stdio:/dev/stdout listed inventoried
access_log stdio:/dev/stdout unlisted !inventoried
acl private dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4 ::/128 ::1/128 fc00::/7 fe80::/10 ff00::/8
http_access deny !api
http_access deny !connect
http_access deny !tls_port
{enforcement}
http_access deny private
http_access allow api
http_access deny all
acl step1 at_step SslBump1
{reject}
ssl_bump peek step1
{splice}
ssl_bump terminate all
shutdown_lifetime 1 seconds
connect_timeout 10 seconds
request_timeout 30 seconds
"""


def main() -> None:
    role = sys.argv[1]
    if role == 'netguard':
        os.execv('/bin/sh', ['sh', str(ROOT / 'firewall.sh')])
    if role == 'proxy':
        config = squid_config(os.environ.get('EGRESS_MODE', 'audit'), os.environ['EGRESS_SUPABASE_HOST'])
        Path('/tmp/squid.conf').write_text(config)
        # Squid requires a certificate to enable ClientHello inspection. This
        # ephemeral certificate can serve local access-denied TLS errors. It is
        # never trusted by clients; permitted traffic is spliced unchanged.
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', '/tmp/key.pem', '-out', '/tmp/cert.pem', '-days', '1',
                        '-subj', '/CN=unused-egress.invalid'], check=True, capture_output=True)
        Path('/tmp/proxy.pem').write_bytes(Path('/tmp/key.pem').read_bytes() + Path('/tmp/cert.pem').read_bytes())
        os.execvp('squid', ['squid', '-N', '-f', '/tmp/squid.conf'])
    if role == 'database':
        host = hostname(os.environ['EGRESS_DB_HOST'])
        # Session pooler/direct DB only. No client-selected target or DNS input.
        if not (host.endswith('.pooler.supabase.com') or re.fullmatch(r'db\.[a-z0-9]+\.supabase\.co', host)):
            raise ValueError('EGRESS_DB_HOST must be a Supabase DB or session pooler hostname')
        Path('/tmp/haproxy.cfg').write_text(f'''global
    log stdout format raw local0
    maxconn 100
defaults
    mode tcp
    timeout connect 10s
    timeout client 1h
    timeout server 1h
resolvers docker
    nameserver dns 127.0.0.11:53
    hold valid 30s
frontend postgres
    bind :5432
    acl api src 172.30.87.2
    tcp-request connection reject if !api
    default_backend database
backend database
    server database {host}:5432 resolvers docker init-addr libc,none
''')
        os.execvp('haproxy', ['haproxy', '-W', '-db', '-f', '/tmp/haproxy.cfg'])
    raise ValueError('unknown sidecar role')


if __name__ == '__main__':
    main()

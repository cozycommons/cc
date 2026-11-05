"""Run inside the real, unprivileged API image; no production credentials."""
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import socket
import ssl
import struct
import sys
import urllib.error
import urllib.request
import uuid

import httpx
import psycopg
import requests
from supabase import create_client


def blocked(call):
    try:
        call()
    except (OSError, httpx.ProxyError, httpx.ConnectError, requests.exceptions.ProxyError):
        return
    raise AssertionError('operation unexpectedly succeeded')


def probe():
    assert os.getuid() != 0
    # Each library must send CONNECT through the proxy. The .test host must be
    # denied by Squid, not fail later on DNS or an unavailable upstream.
    # Squid's ssl-bump denial uses a local TLS error certificate; it is never
    # trusted. Logs must independently confirm TCP_DENIED for all five clients.
    url = 'https://must-not-resolve.example.test/'
    try:
        urllib.request.urlopen(url, timeout=3)
    except urllib.error.URLError as exc:
        assert '403' in str(exc) or 'CERTIFICATE_VERIFY_FAILED' in str(exc), exc
    else:
        raise AssertionError('urllib bypassed proxy')
    with httpx.Client(timeout=3) as client:
        try:
            client.get(url)
        except (httpx.ProxyError, httpx.ConnectError) as exc:
            assert '403' in str(exc) or 'CERTIFICATE_VERIFY_FAILED' in str(exc), exc
        else:
            raise AssertionError('httpx bypassed proxy')

    async def async_httpx():
        async with httpx.AsyncClient(timeout=3) as client:
            try:
                await client.get(url)
            except (httpx.ProxyError, httpx.ConnectError) as exc:
                assert '403' in str(exc) or 'CERTIFICATE_VERIFY_FAILED' in str(exc), exc
            else:
                raise AssertionError('async httpx bypassed proxy')
    asyncio.run(async_httpx())
    try:
        requests.get(url, timeout=3)
    except (requests.exceptions.ProxyError, requests.exceptions.SSLError) as exc:
        assert '403' in str(exc) or 'CERTIFICATE_VERIFY_FAILED' in str(exc), exc
    else:
        raise AssertionError('requests bypassed proxy')
    supabase = create_client(url, 'synthetic-only')
    try:
        supabase.table('synthetic').select('*').execute()
    except (httpx.ProxyError, httpx.ConnectError) as exc:
        assert '403' in str(exc) or 'CERTIFICATE_VERIFY_FAILED' in str(exc), exc
    else:
        raise AssertionError('Supabase bypassed proxy')
    print('PASS urllib, sync/async httpx, requests, Supabase use HTTPS_PROXY', flush=True)

    # Public, credential-free GET, with endpoint certificate validation intact.
    for host in Path('/egress-hosts.txt').read_text().splitlines():
        if not host or host.startswith('#'):
            continue
        with httpx.Client(timeout=20) as client:
            response = client.get(f'https://{host}/')
            print(f'PASS allowed TLS {host}: HTTP {response.status_code}', flush=True)

    for address in [('1.1.1.1', 443), ('172.30.87.1', 80), ('172.30.87.3', 80),
                    ('172.30.87.4', 80), ('127.0.0.11', 53), ('2606:4700:4700::1111', 443)]:
        blocked(lambda: socket.create_connection(address, timeout=.4))
    with httpx.Client(trust_env=False, timeout=.4) as client:
        blocked(lambda: client.get('https://1.1.1.1/'))
    print('PASS direct IPv4/IPv6, gateway, sibling ports, proxy-env bypass refused', flush=True)

    for authority in ['example.com:443', 'secret.api.resy.com:443', '1.1.1.1:443',
                      'api.resy.com:80', 'api.resy.com:5432', 'localhost:443']:
        with socket.create_connection(('172.30.87.3', 3128), timeout=3) as conn:
            conn.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n'.encode())
            status = conn.recv(4096).split(b'\r\n')[0]
            if b'200' in status:
                blocked(lambda: ssl.create_default_context().wrap_socket(conn, server_hostname=authority.split(':')[0]))
            else:
                assert b'403' in status, authority
    # A permitted CONNECT name must not tunnel TLS to an unlisted SNI host.
    def wrong_sni():
        conn = socket.create_connection(('172.30.87.3', 3128), timeout=3)
        conn.sendall(b'CONNECT api.resy.com:443 HTTP/1.1\r\nHost: api.resy.com:443\r\n\r\n')
        assert b'200' in conn.recv(4096).split(b'\r\n')[0]
        try:
            ssl.create_default_context().wrap_socket(conn, server_hostname='example.com')
        finally:
            conn.close()
    blocked(wrong_sni)
    print('PASS unlisted/subdomain/IP/port CONNECT and unlisted SNI refused', flush=True)

    marker = 'egress-' + uuid.uuid4().hex + '.example.test'
    packet = struct.pack('!6H', 1234, 0x100, 1, 0, 0, 0) + b''.join(
        bytes([len(part)]) + part.encode() for part in marker.split('.')) + b'\0\0\1\0\1'
    for destination in ['127.0.0.11', '8.8.8.8', '172.30.87.3']:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conn:
            conn.settimeout(.3)
            def dns_request():
                conn.sendto(packet, (destination, 53))
                conn.recv(1024)
            blocked(dns_request)
    socket.setdefaulttimeout(.3)
    blocked(lambda: socket.getaddrinfo(marker, 443))
    print(f'PASS DNS sockets and getaddrinfo blocked; capture marker={marker}', flush=True)

    with psycopg.connect('postgresql://postgres:synthetic-egress-only@synthetic.pooler.supabase.com:5432/postgres', connect_timeout=3) as db:
        assert db.execute('select 12345').fetchone() == (12345,)
    print('PASS PostgreSQL relay with synthetic local database', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        assert os.environ['EGRESS_SECRET_SENTINEL'] == 'synthetic-$literal-only'
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'synthetic-egress-api\n')
        HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
    else:
        probe()

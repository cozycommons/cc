#!/bin/sh
# Linux container entrypoint, never run on the host. No API process has NET_ADMIN.
set -eu
for tool in iptables ip6tables; do
    "$tool" -P OUTPUT DROP
    "$tool" -P FORWARD DROP
    "$tool" -P INPUT DROP
    "$tool" -A INPUT -m conntrack --ctstate ESTABLISHED -j ACCEPT
    "$tool" -A OUTPUT -m conntrack --ctstate ESTABLISHED -j ACCEPT
    case "$tool" in iptables) loopback=127.0.0.1 ;; ip6tables) loopback=::1 ;; esac
    "$tool" -A INPUT -i lo -s "$loopback" -p tcp -m multiport --dports 8000,8001 -j ACCEPT
    "$tool" -A OUTPUT -o lo -d "$loopback" -p tcp -m multiport --dports 8000,8001 -j ACCEPT
done
iptables -A INPUT -s 172.30.87.0/24 -p tcp --dport 8000 -j ACCEPT
iptables -A OUTPUT -d 172.30.87.3 -p tcp --dport 3128 -j ACCEPT
iptables -A OUTPUT -d 172.30.87.4 -p tcp --dport 5432 -j ACCEPT
# Drop DNS before Docker's OUTPUT DNAT to an ephemeral resolver port. Default
# filter DROP also blocks attempts to discover and use that translated port.
for tool in iptables ip6tables; do
    "$tool" -t raw -A OUTPUT -p udp --dport 53 -j DROP
    "$tool" -t raw -A OUTPUT -p tcp --dport 53 -j DROP
done
exec python3 /opt/egress/ready.py

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    squid-openssl openssl ca-certificates python3 iptables haproxy tcpdump \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/api-egress /opt/egress
ENTRYPOINT ["python3", "/opt/egress/start.py"]

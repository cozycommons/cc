FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends bash curl git nodejs npm supervisor postgresql-client ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir psycopg[binary]==3.2.13
COPY infra/apps/runtime/entrypoint.sh /usr/local/bin/app-start
COPY infra/apps/runtime/supervisord.conf /etc/supervisor/supervisord.conf
COPY infra/apps/runtime/AGENTS.md /opt/app-AGENTS.md
COPY infra/apps/runtime/commons.py /usr/local/bin/commons
RUN chmod +x /usr/local/bin/app-start /usr/local/bin/commons
ENV HOME=/workspace/home
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/app-start"]

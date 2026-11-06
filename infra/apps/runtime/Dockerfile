FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends bash curl git nodejs npm supervisor postgresql-client ca-certificates && rm -rf /var/lib/apt/lists/*
COPY infra/apps/runtime/requirements.txt /opt/runtime-requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    PIP_CERT=${PIP_CERT:-/run/secrets/proxy_ca} sh -c '[ -f "$PIP_CERT" ] || unset PIP_CERT; pip install --no-cache-dir --require-hashes --only-binary=:all: -r /opt/runtime-requirements.txt'
COPY infra/apps/runtime/entrypoint.sh /usr/local/bin/app-start
COPY infra/apps/runtime/supervisord.conf /etc/supervisor/supervisord.conf
COPY infra/apps/runtime/AGENTS.md /opt/app-AGENTS.md
COPY infra/apps/runtime/initialize_repo.py /opt/initialize_repo.py
COPY infra/apps/runtime/gitignore /opt/app-gitignore
COPY infra/apps/runtime/commons.py /usr/local/bin/commons
RUN chmod +x /usr/local/bin/app-start /usr/local/bin/commons
ENV HOME=/workspace/home
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/app-start"]

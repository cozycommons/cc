FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/app_runtime/requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    PIP_CERT=${PIP_CERT:-/run/secrets/proxy_ca} sh -c '[ -f "$PIP_CERT" ] || unset PIP_CERT; pip install --no-cache-dir --require-hashes --only-binary=:all: -r /app/requirements.txt'
COPY backend/app_runtime /app/app_runtime
CMD ["uvicorn", "app_runtime.api:app", "--host", "0.0.0.0", "--port", "9000"]

# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --include=optional
COPY frontend/ ./
COPY shared/commons/ /shared/commons/
COPY design/ /design/
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_SUPABASE_URL=${VITE_SUPABASE_URL} \
    VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}
RUN npm run build -- --base=/crowdset/ && node scripts/check-bundle-size.js

FROM python:3.12-slim
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
RUN node --version
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    CROWDSET_DATA_DIR=/data CROWDSET_STATIC_DIR=/static
WORKDIR /app
COPY backend/requirements-crowdset.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt \
    && groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir /data && chown app:app /data
COPY --chown=app:app backend/crowdset/ /app/crowdset/
COPY --from=frontend /app/dist /static
USER app
EXPOSE 8010
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/crowdset/health', timeout=2).read()" || exit 1
CMD ["python", "-m", "uvicorn", "crowdset.app:app", "--host", "0.0.0.0", "--port", "8010", "--no-proxy-headers", "--timeout-graceful-shutdown", "10"]

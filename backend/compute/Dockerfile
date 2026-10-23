FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 CC_COMPUTE_DB=/data/jobs.sqlite3
WORKDIR /app
COPY backend/requirements-compute.txt /app/requirements-compute.txt
RUN pip install --no-cache-dir -r requirements-compute.txt \
    && groupadd --system app && useradd --system --gid app app \
    && mkdir /data && chown app:app /data
COPY --chown=app:app backend/ /app/
USER app
EXPOSE 8011
CMD ["python", "-m", "uvicorn", "compute.api:configured_app", "--factory", "--host", "0.0.0.0", "--port", "8011"]

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/app_runtime/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend/app_runtime /app/app_runtime
CMD ["uvicorn", "app_runtime.api:app", "--host", "0.0.0.0", "--port", "9000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WEBULL_OPENAPI_TOKEN_DIR=/data/webull-token

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

RUN useradd --create-home appuser && mkdir -p /data/webull-token && chown -R appuser /data
USER appuser

EXPOSE 8000
# The worker service overrides this with: python -m app.scheduler
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

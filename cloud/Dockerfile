FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install "fastapi>=0.115" "uvicorn>=0.30"
COPY sync_app.py .
EXPOSE 8300
CMD ["uvicorn", "sync_app:app", "--host", "0.0.0.0", "--port", "8300"]

# NEXORA backend container.
# Build:  docker build -t nexora-backend .
# Run:    docker run -p 8000:8000 --env-file .env nexora-backend
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/nexora

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# One worker on purpose: conversation context lives in memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

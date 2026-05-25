FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-postgres-ingest.txt .
RUN pip install --no-cache-dir -r requirements-postgres-ingest.txt

COPY trucks_postgres_ingest.py schema.sql ./

CMD ["python", "trucks_postgres_ingest.py", "--loop", "--sleep", "60"]

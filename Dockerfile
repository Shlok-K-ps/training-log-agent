FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY chat.py ./

# Local SQLite fallback only. Any deployment must set DATABASE_URL (Postgres) so
# the agent's memory survives restarts and redeploys.
RUN mkdir -p /srv/data
ENV DATABASE_PATH=/srv/data/training_log.db

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

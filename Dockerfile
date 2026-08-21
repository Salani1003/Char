FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Valores dummy sólo para que `collectstatic` pueda importar settings.py en
# build time (no toca la base). En runtime, docker-compose los pisa con el
# .env real vía `env_file`.
RUN SECRET_KEY=build-time-placeholder \
    DB_NAME=build DB_USER=build DB_PASSWORD=build DB_HOST=localhost DB_PORT=5432 \
    python manage.py collectstatic --noinput

RUN useradd --create-home appuser \
    && mkdir -p staticfiles \
    && chown -R appuser:appuser /app
USER appuser

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

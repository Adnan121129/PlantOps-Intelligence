FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --create-home --uid 1000 plantops
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN mkdir -p /app/staticfiles /app/media && chown -R plantops /app
USER plantops
EXPOSE 8000
# Migrations run on start; seeding is an explicit, separate command (see README).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput >/dev/null && gunicorn plantops.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout 120 --access-logfile -"]

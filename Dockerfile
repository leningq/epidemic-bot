FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/app/data/epidemic.sqlite3 \
    MEDIA_DIR=/app/media

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY epidemic ./epidemic
COPY tools ./tools

RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data /app/media \
    && chown -R bot:bot /app/data

USER bot

# Бот каждые 15 секунд обновляет data/.heartbeat — если файл не меняется 2 минуты, контейнер нездоров.
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,sys,time; p='/app/data/.heartbeat'; sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 120 else 1)"

CMD ["python", "-m", "epidemic"]

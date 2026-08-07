FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 1000 app

COPY --chown=app:app avito_reminder ./avito_reminder
COPY --chown=app:app pyproject.toml README.md ./

RUN mkdir -p /app/data && chown -R app:app /app

USER app

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD ["python", "-m", "avito_reminder.cli"]

CMD ["python", "-m", "avito_reminder"]

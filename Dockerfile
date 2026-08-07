# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY --chown=app:app . .
RUN mkdir -p /app/data \
    && chown app:app /app/data

USER app

EXPOSE 8000 8501

ENTRYPOINT ["sh", "scripts/start_prod.sh"]

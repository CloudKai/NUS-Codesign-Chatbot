# syntax=docker/dockerfile:1
# Architecture-neutral base. Build for EC2 t4g (ARM64) with:
#   docker buildx build --platform linux/arm64 -t <ECR_IMAGE_URI>:<tag> --push .
FROM python:3.12-slim

ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_GIT_SHA="${GIT_SHA}"

WORKDIR /app

# Trusted CAs for psycopg sslmode=verify-full / sslrootcert=system (DSQL).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY --chown=app:app . .
# /app/data is optional for local/sqlite images only. Production DSQL+S3
# containers do not mount or require persistent student data here.
RUN mkdir -p /app/data /tmp/co-design \
    && chown app:app /app/data /tmp/co-design

USER app

EXPOSE 8000 8501

ENTRYPOINT ["sh", "scripts/start_prod.sh"]

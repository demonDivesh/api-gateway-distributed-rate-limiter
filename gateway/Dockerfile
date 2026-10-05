# syntax=docker/dockerfile:1
# Python is pinned to the 3.14 line. To pin an exact patch release (e.g. 3.14.6) build with:
#   docker build --build-arg PYTHON_IMAGE=python:3.14.6-slim gateway
ARG PYTHON_IMAGE=python:3.14-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# Several workers are safe: all shared state (rate limits, token revocation) lives in Redis.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header", "--proxy-headers"]

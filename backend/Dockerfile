FROM python:3.10-slim

# Mirror / proxy settings intentionally disabled by default.
# ARG PIP_INDEX_URL=https://mirror-pypi.runflare.com/simple
# ARG PIP_TRUSTED_HOST=mirror-pypi.runflare.com
# ARG HTTP_PROXY=
# ARG HTTPS_PROXY=
# ARG http_proxy=
# ARG https_proxy=
# ARG ALL_PROXY=
# ARG all_proxy=
# ARG NO_PROXY=*
# ARG no_proxy=*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=20

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install \
      --timeout 300 \
      --retries 20 \
      --upgrade pip && \
    python -m pip install \
      --timeout 300 \
      --retries 20 \
      -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/storage

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

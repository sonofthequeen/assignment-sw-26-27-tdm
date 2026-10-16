# Backend API image (Python 3.12). Migrations run at container start; demo data
# is seeded only when SEED_DEMO_DATA=true.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_URL=sqlite:////data/tdm.sqlite3 \
    SEED_DEMO_DATA=false

WORKDIR /app

# Dependencies first (cached layer), pinned by constraints.txt.
COPY pyproject.toml constraints.txt ./
COPY app ./app
# Install, then drop the local build artefacts (the app runs from /app/app).
RUN pip install -c constraints.txt . \
    && rm -rf build race_up_tdm.egg-info

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY sample-data ./sample-data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 tdm \
    && mkdir -p /data \
    && chown tdm:tdm /data
USER tdm

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=2)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

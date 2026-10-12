FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

WORKDIR /app

# DejaVu supports Unicode text in exported CVs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends zlib1g-dev fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 studentreplica \
    && useradd --uid 10001 --gid studentreplica --create-home \
        --shell /usr/sbin/nologin studentreplica

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && python -m pip check

COPY --chown=studentreplica:studentreplica . .
RUN mkdir -p /app/database /app/data \
    && chown studentreplica:studentreplica /app/database /app/data

USER studentreplica

VOLUME ["/app/database"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"]

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]

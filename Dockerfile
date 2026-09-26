# Ex Libris — one small image, two ports, one data folder.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EXLIBRIS_DATA=/data
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY exlibris ./exlibris
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN pip install --no-compile . \
 && useradd --uid 1000 --create-home --shell /usr/sbin/nologin exlibris \
 && mkdir -p /data && chown exlibris:exlibris /data
# runs as root only to fix /data ownership, then drops to PUID/PGID (default 1000)
VOLUME ["/data"]
EXPOSE 8080 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "exlibris"]

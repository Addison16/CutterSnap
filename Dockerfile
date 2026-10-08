FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY cuttersnap ./cuttersnap
RUN pip install .

RUN useradd --create-home cutter && mkdir /data && chown cutter /data
ENV CUTTERSNAP_DATA=/data
VOLUME /data
USER cutter
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["uvicorn", "cuttersnap.api:app", "--host", "0.0.0.0", "--port", "8080"]

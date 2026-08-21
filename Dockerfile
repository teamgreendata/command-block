FROM python:3.12.13-slim

WORKDIR /srv/command-block

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

RUN useradd --create-home --uid 10001 dash
# /cb-data holds waypoints.json; the named volume inherits this ownership on
# first use so the non-root user can write it
RUN mkdir /cb-data && chown dash /cb-data
USER dash

ENV DASH_PORT=8300

# slim has no curl — probe /healthz with the stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DASH_PORT','8300'), timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${DASH_PORT:-8300}"]

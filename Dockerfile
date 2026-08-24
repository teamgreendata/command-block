FROM python:3.12.13-slim

WORKDIR /srv/command-block

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# uid 1000 matches the minecraft container's user: the server writes
# playerdata .dat files as 600, so any other uid can't read XP/health/food
RUN useradd --create-home --uid 1000 dash
RUN mkdir /cb-data && chown dash /cb-data

ENV DASH_PORT=8300

# slim has no curl — probe /healthz with the stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DASH_PORT','8300'), timeout=4).status == 200 else 1)"

# starts as root, chowns the volume, drops to dash (see entrypoint.sh)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Pterodactyl convention: run as the unprivileged "container" user with
# /home/container as home. The code itself lives in /app because Pterodactyl
# mounts its server volume over /home/container.
RUN useradd -m -d /home/container -s /bin/sh container

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

EXPOSE 4530 4531 4532 4533

# Runtime variables can be overridden by Docker or Pterodactyl.
ENV LISTEN_HOST=0.0.0.0 \
    PUBLIC_IP=127.0.0.1 \
    REGION=local \
    MAX_PLAYERS=4

USER container
ENV USER=container HOME=/home/container

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "python main.py local -l ${LISTEN_HOST} -i ${PUBLIC_IP} -r ${REGION} --max-players ${MAX_PLAYERS}"]

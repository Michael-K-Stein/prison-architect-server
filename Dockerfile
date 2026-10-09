FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 4530 4531 4532 4533

# Runtime variables can be overridden by Docker or Pterodactyl.
ENV LISTEN_HOST=0.0.0.0 \
    PUBLIC_IP=127.0.0.1 \
    TIMEOUT=30 \
    REGION=local \
    MAX_PLAYERS=4

CMD ["sh", "-c", "python main.py local -l ${LISTEN_HOST} -i ${PUBLIC_IP} --timeout ${TIMEOUT} -r ${REGION} --max-players ${MAX_PLAYERS}"]

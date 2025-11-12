ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip sqlite

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /data

EXPOSE 8100

CMD ["python3", "-m", "waitress", "--host=0.0.0.0", "--port=8100", "app.main:app"]

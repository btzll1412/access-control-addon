ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

# Install requirements
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite

WORKDIR /app

# Copy requirements and install with break-system-packages flag
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy app files
COPY app/ ./app/
COPY templates/ ./templates/
COPY run.sh ./

RUN chmod a+x run.sh

CMD ["./run.sh"]

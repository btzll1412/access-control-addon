ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG=C.UTF-8

# Install requirements
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy app files
COPY app/ ./app/
COPY templates/ ./templates/
COPY run.sh ./

# Debug: List files to verify they're copied
RUN ls -la /app/
RUN ls -la /app/templates/

RUN chmod a+x run.sh

CMD ["./run.sh"]

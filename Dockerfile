ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python and dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy app files
COPY app/ ./app/

# Copy run script
COPY run.sh ./

# Create data directory
RUN mkdir -p /data

# Make run script executable
RUN chmod +x run.sh

# Expose port
EXPOSE 8100

# Labels
LABEL \
    io.hass.name="Access Control System" \
    io.hass.description="ESP32 Access Control System" \
    io.hass.arch="amd64|aarch64|armv7" \
    io.hass.type="addon" \
    io.hass.version="1.0.0"

# Run the application
CMD ["./run.sh"]

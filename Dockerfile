ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-flask \
    py3-requests \
    sqlite \
    bash

# Copy application files
COPY app /app

# Set working directory
WORKDIR /app

# Install Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages \
    waitress==2.1.2

# Expose port
EXPOSE 8100

# Run directly without shell script
CMD ["python3", "-m", "waitress", "--host=0.0.0.0", "--port=8100", "main:app"]

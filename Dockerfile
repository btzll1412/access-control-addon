ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-flask \
    py3-requests \
    sqlite

# Copy application files
COPY app /app

# Set working directory
WORKDIR /app

# Install Python dependencies with --break-system-packages flag
RUN pip3 install --no-cache-dir --break-system-packages \
    waitress==2.1.2

# Copy run script
COPY run.sh /
RUN chmod a+x /run.sh

# Expose port
EXPOSE 8100

# Run
CMD [ "/run.sh" ]

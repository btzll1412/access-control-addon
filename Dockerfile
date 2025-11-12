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

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    waitress==2.1.2 \
    flask==2.3.2 \
    requests==2.31.0

# Copy run script
COPY run.sh /
RUN chmod a+x /run.sh

# Expose port
EXPOSE 8100

# Run
CMD [ "/run.sh" ]

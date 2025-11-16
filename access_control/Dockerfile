FROM python:3.11-alpine

# Install system dependencies
RUN apk add --no-cache sqlite

# Set working directory
WORKDIR /app

RUN pip install pytz

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8100

# Run the application directly
CMD ["python3", "-m", "waitress", "--host=0.0.0.0", "--port=8100", "app.main:app"]

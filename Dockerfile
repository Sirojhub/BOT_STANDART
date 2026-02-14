# Python 3.11-slim image for smaller size and security
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if any needed for aiosqlite/build)
# sqlite3 is usually included in slim, but good to ensure
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite persistence
# This is where the volume should be mounted
RUN mkdir -p data

# Set environment variable to ensure output logs are sent to terminal directly
ENV PYTHONUNBUFFERED=1

# Expose Render's default port (though Render ignores EXPOSE, it's good practice)
EXPOSE 10000

# Command to run the bot
CMD ["python", "main.py"]

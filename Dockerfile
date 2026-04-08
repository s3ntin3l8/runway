FROM python:3.12-slim-bookworm

# Create non-root user with home directory
RUN groupadd -r runway && useradd -r -g runway -u 1000 -m runway

WORKDIR /app

# Install system dependencies (including Node.js for Tailwind CSS build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libsqlite3-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy and install Python dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy package files and install Node dependencies
COPY package.json package-lock.json* ./
RUN npm ci

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY frontend/ ./frontend/
COPY tailwind.config.js ./

# Build Tailwind CSS
RUN npm run build:css

# Remove Node.js and npm to reduce image size
RUN apt-get remove -y nodejs curl && apt-get autoremove -y \
    && rm -rf node_modules package.json package-lock.json* tailwind.config.js

# Set ownership to non-root user
RUN chown -R runway:runway /app

# Switch to non-root user
USER runway

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8765

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/limits')" || exit 1

# Run application
CMD ["python3", "-m", "app.main"]

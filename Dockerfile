FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for pydub/audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-3001}/api/health')" || exit 1

EXPOSE 3001

CMD ["python3", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "3001"]

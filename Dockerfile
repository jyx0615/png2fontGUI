# Production Dockerfile for deploying png2font API to a public cloud (Railway, Render, Fly.io)
FROM python:3.11-slim

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install native FontForge and system utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    fontforge \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set standard working directory
WORKDIR /app

# Copy dependency configs
COPY requirements.txt /app/

# Install FastAPI, Uvicorn, and core pipeline packages
RUN pip install --no-cache-dir \
    -r requirements.txt \
    fastapi \
    uvicorn \
    python-multipart \
    requests

# Copy remaining source code and asset files
COPY . /app/

# Download the Linux x86_64 svgcleaner binary (replaces the macOS binary copied above)
RUN curl -sL https://github.com/RazrFalcon/svgcleaner/releases/download/v0.9.5/svgcleaner_linux_x86_64_0.9.5.tar.gz \
    | tar -xz -C /usr/local/bin/ svgcleaner && chmod +x /usr/local/bin/svgcleaner

# Expose default API server port
EXPOSE 3000

# Start Uvicorn engine
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]

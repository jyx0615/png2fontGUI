# Production Dockerfile for deploying png2font API to a public cloud (Railway, Render, Fly.io)
FROM python:3.11-slim

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install native FontForge and system utilities
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    fontforge \
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

# Ensure pre-compiled svgcleaner is executable inside the container
RUN chmod +x /app/svgcleaner

# Expose default API server port
EXPOSE 8000

# Start Uvicorn engine
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

# Base image: matches the Python version the project's venv uses (3.13.6),
# slim variant keeps the image small since we install ffmpeg separately below.
FROM python:3.13-slim

# Prevents Python from writing .pyc files and buffering stdout/stderr,
# so `docker compose logs` shows output immediately instead of batching it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ffmpeg is a hard runtime dependency of pipeline/overlay.py (invoked via
# subprocess, not a pip package) — without it, rendering fails at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so `pip install` is cached in its own layer and
# only reruns when dependencies actually change, not on every code edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project; in dev this gets overridden by the
# docker-compose bind mount so local edits show up without a rebuild.
COPY . .

# Runs migrate + collectstatic before handing off to CMD — shared by both the
# prod gunicorn command below and the runserver override in dev's docker-compose.yml.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 8000

# Production default: gunicorn bound to 0.0.0.0 so nginx (a separate container) can
# reach it; dev's docker-compose.yml overrides this back to `runserver` for autoreload.
CMD ["gunicorn", "video_editing_agent.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]

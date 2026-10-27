# FixLoop Backend Dockerfile
FROM python:3.11-slim

# Avoid writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend code, pyproject, and benchmark scenarios
COPY backend/ ./backend/
COPY scenarios/ ./scenarios/
COPY sample_project/ ./sample_project/
COPY pyproject.toml ./pyproject.toml

# Create unprivileged user for secure execution
RUN useradd -u 1001 -m fixloop && chown -R fixloop:fixloop /app
USER fixloop

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

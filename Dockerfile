# Build stage
FROM python:3.12.9-slim as builder

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies only (not the package itself)
RUN poetry install --only main --no-interaction --no-ansi

# Runtime stage
FROM python:3.12.9-slim

WORKDIR /app

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=app:app bridge/ ./bridge/

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV HOST=0.0.0.0
ENV PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:${PORT}/health').raise_for_status()"

# Run the application
CMD ["python", "-m", "uvicorn", "bridge.app:app", "--host", "0.0.0.0", "--port", "8080"]

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
COPY scripts ./scripts
# Docker named volumes inherit mount-point ownership only if the directories
# already exist in the image. Prepare both writable mounts before USER switch.
RUN useradd --create-home appuser \
    && mkdir -p /app/.state /app/.vector_data \
    && chown -R appuser:appuser /app /home/appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

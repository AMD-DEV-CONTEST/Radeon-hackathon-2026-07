FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    SQLITE_DB_PATH=/app/data/educopilot.db \
    CHROMA_PERSIST_DIR=/app/data/chroma_data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/data

EXPOSE 7860

CMD ["python", "webapp.py"]
FROM python:3.12-slim

WORKDIR /app

COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=1
ENV COMFY_URL=http://host.docker.internal:8188
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
RUN pip install --no-cache-dir redis
WORKDIR /opt/2sin-stack/scheduler
EXPOSE 8788
CMD ["python3", "/opt/2sin-stack/scheduler/scheduler.py"]

FROM rocm/pytorch:latest

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV TORCH_HOME=/workspace/persistent/silent-vision/cache/torch

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r /app/requirements.txt

COPY . /app

CMD ["uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"]

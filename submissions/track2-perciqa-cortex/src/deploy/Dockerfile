FROM rocm/pytorch:latest

WORKDIR /app

COPY pyproject.toml README.md ./
COPY cortex/ ./cortex/

RUN pip install --no-cache-dir -e ".[gpu]" && \
    pip install --no-cache-dir vllm

EXPOSE 7432 8000 8080 9464

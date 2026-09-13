FROM rocm/pytorch:latest

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    xvfb \
    libgl1 \
    libglib2.0-0 \
    libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Make bundled Genesis source importable when evaluators use the notebook or
# ROCm setup checker.
RUN if [ -f Genesis/pyproject.toml ]; then pip install --no-cache-dir -e Genesis; fi

# Create directories for outputs
RUN mkdir -p models logs output

# Expose for Jupyter (optional)
EXPOSE 8888

# Default: run demo
CMD ["python", "demo.py", "--episodes", "1"]

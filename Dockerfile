# Base image optimized for AMD ROCm and PyTorch
FROM rocm/pytorch:rocm6.0_ubuntu22.04_py3.10

# Set environment variables for non-interactive installs and Vulkan
ENV DEBIAN_FRONTEND=noninteractive
ENV VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.x86_64.json

# Install system dependencies for Genesis (Vulkan) and video rendering (FFmpeg)
RUN apt-get update && apt-get install -y \
    vulkan-tools \
    libvulkan1 \
    mesa-vulkan-drivers \
    ffmpeg \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the entire project repository into the container
COPY . /app

# Install all required Python packages
# (Assuming your setup.sh or requirements.txt handles this)
RUN pip install --upgrade pip
RUN pip install genesis-world==1.3.1 pymilvus[model] torch transformers accelerate ultralytics

# Command to execute the R.A.G.E pipeline
CMD ["python3", "-m", "project.scripts.run_pipeline"]
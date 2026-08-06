# Zivra Vision

Multimodal AI hackathon submission — text-to-image generation using SDXL-Turbo.

## Team
Zivra

## Setup
pip install -r requirements.txt

## Run
python app.py

## Hardware
Developed and demonstrated on CPU (local machine); the code is ROCm-compatible
and runs unmodified on an AMD Radeon GPU with ROCm-enabled PyTorch — swap the
CPU torch install in requirements.txt for the ROCm build to run on Radeon GPU.
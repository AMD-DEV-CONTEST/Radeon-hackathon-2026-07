# 🚀 Zivra Vision
### Multimodal AI Text-to-Image Generation Platform
**AMD AI DevMaster Hackathon 2026 – Track 1: Multimodal AI**

---

## 📌 Overview

Zivra Vision is a multimodal AI application that transforms natural language prompts into high-quality images using Stable Diffusion. The platform provides an intuitive web interface where users can enter descriptive text and generate AI-created artwork in seconds.

The application is designed to leverage AMD Radeon™ GPUs and the ROCm™ software stack for accelerated AI inference while maintaining compatibility with CPU execution for portability and accessibility.

---

# ✨ Features

- 🎨 Text-to-Image Generation
- 🧠 Stable Diffusion AI Model
- ⚡ AMD Radeon GPU / ROCm Support
- 💻 CPU Fallback Support
- 🌐 Interactive Gradio Web Interface
- 🎛 Adjustable Inference Steps
- 🎯 Configurable Guidance Scale
- 🖼 High-Quality AI Image Generation
- 🔄 Cross-Platform Compatibility

---

# 🏗 Architecture

```
User Prompt
      │
      ▼
Gradio Web Interface
      │
      ▼
Stable Diffusion Pipeline
      │
      ▼
PyTorch Inference Engine
      │
      ▼
AMD Radeon GPU (ROCm)
      │
      ▼
Generated Image
```

---

# 🛠 Technology Stack

| Component | Technology |
|-----------|------------|
| Programming Language | Python |
| AI Framework | PyTorch |
| Diffusion Library | Hugging Face Diffusers |
| Transformers | Hugging Face Transformers |
| UI Framework | Gradio |
| Image Generation | Stable Diffusion |
| Hardware Acceleration | AMD Radeon GPUs + ROCm |

---

# 🚀 Installation

Clone the repository

```bash
git clone https://github.com/sangamithra731/Radeon-hackathon-2026-07.git

cd Radeon-hackathon-2026-07
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run the application

```bash
python app.py
```

Open your browser

```
http://127.0.0.1:7860
```

---

# 📷 Workflow

1. Launch the application.
2. Enter a descriptive text prompt.
3. Select inference settings.
4. Click **Generate Image**.
5. View the AI-generated image instantly.

---

# 💡 Example Prompts

- A futuristic smart city at sunset
- A cyberpunk cat wearing sunglasses
- Ancient temple hidden inside a rainforest
- Space station orbiting Saturn
- Underwater kingdom with glowing corals

---

# 🎯 AMD GPU Optimization

Zivra Vision automatically detects GPU availability using PyTorch.

- AMD Radeon GPU Support
- ROCm Acceleration
- Automatic Device Detection
- CPU Fallback
- Optimized AI Inference

---

# 📈 Future Enhancements

- Image-to-Image Generation
- AI Image Editing
- Style Transfer
- Inpainting
- Image Upscaling
- Prompt History
- Model Selection
- Batch Image Generation

---

# 🌍 Real-World Applications

- Digital Art
- Marketing & Advertising
- Game Asset Creation
- Storyboarding
- Education
- Graphic Design
- Content Creation
- Concept Art

---

# 👩‍💻 Developer

**Sangamithra**

AMD AI DevMaster Hackathon 2026

Track 1 – Multimodal AI

---

# 📜 License

This project is developed for educational and hackathon purposes under the AMD AI DevMaster Hackathon 2026.

---

# ⭐ Acknowledgements

- AMD AI DevMaster Hackathon
- AMD Radeon™ GPU Team
- ROCm™ Software Platform
- Hugging Face
- PyTorch
- Gradio
- Open Source AI Community

---

## 🎉 Thank You

Thank you for reviewing **Zivra Vision**.

Building the future of Multimodal AI with AMD Radeon GPUs.

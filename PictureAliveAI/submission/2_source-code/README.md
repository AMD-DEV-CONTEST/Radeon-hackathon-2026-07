
<div align="center">

# 🖼️ PICTURE ALIVE AI
### **Beyond Imagination**

### Making the Future Alive with Multimodal AI

<img width="2061" height="763" alt="PICTURE_ALIVE_AI_COVER_IMAGE_RESIZE" src="https://github.com/user-attachments/assets/39aba44f-91ee-4d7a-9104-96ce1dacb392" />

---

## 🛠️ Technology Stack

![ComfyUI](https://img.shields.io/badge/ComfyUI-Workflow_UI-6A0DAD?style=for-the-badge&logo=nodedotjs&logoColor=white)
![Hugging Face](https://img.shields.io/badge/Hugging_Face-Open_Source_AI-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)
![Gemma 4](https://img.shields.io/badge/Gemma_4-Multimodal_AI-4285F4?style=for-the-badge&logo=google&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Kokoro-82M](https://img.shields.io/badge/Kokoro--82M-Text--to--Speech-FF6F61?style=for-the-badge&logo=soundcloud&logoColor=white)
![AMD Radeon](https://img.shields.io/badge/AMD-Radeon-ED1C24?style=for-the-badge&logo=amd&logoColor=white)
![ROCm](https://img.shields.io/badge/ROCm-GPU_Acceleration-ED1C24?style=for-the-badge&logo=amd&logoColor=white)
![MIT License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge&logo=opensourceinitiative&logoColor=white)


### 🌍 Bringing Images to Life with AI Vision & Smart Narration

[🚀 Live Demo](https://www.youtube.com/watch?v=_9gH0ES8FBw)
|
[📖 Wiki](https://github.com/Poppenspel-Advies/picture-alive-ai/wiki)
|
[🎥 Demo  Audio Heritage & Tourism](https://audiomack.com/poppenspeladvies/song/6a6f3abe19f79)
|
[⭐ Star Repository](https://github.com/Poppenspel-Advies/picture-alive-ai/tree/main/PictureAliveAI)

</div>


## ✨ What is Picture Alive AI?

**Picture Alive AI** is a next-generation **multimodal artificial intelligence platform** that seamlessly transforms static images into immersive, intelligent, and interactive digital experiences. Powered by state-of-the-art AI vision, advanced language models, and natural voice synthesis, the platform transcends traditional image recognition by delivering contextual understanding, rich storytelling, and human-like narration.

Designed for accessibility, education, digital intelligence, cultural preservation, scientific discovery, and enterprise innovation, Picture Alive AI converts every image into a dynamic source of knowledge—bridging the gap between visual perception and intelligent communication.

Whether analyzing wildlife, historical landmarks, consumer products, engineering systems, artworks, medical imagery, or educational content, Picture Alive AI produces comprehensive AI-driven insights accompanied by lifelike voice narration, enabling users to **see beyond the visible and hear beyond the imaginable**.

---

## 🌟 What Picture Alive AI Can Do

Upload any image and Picture Alive AI can intelligently:

- 🧠 **Interpret complex visual scenes** using advanced multimodal AI reasoning.
- 🔍 **Detect, classify, and recognize objects** with high-confidence computer vision.
- 🌍 **Identify geographical locations, landmarks, and environments** with contextual awareness.
- 🐅 **Recognize wildlife and biodiversity**, providing scientific classifications, habitats, conservation status, and behavioral insights.
- 📱 **Analyze consumer products and engineering systems**, generating intelligent technical summaries, specifications, architecture, and market insights.
- 📖 **Explain historical, cultural, and scientific significance** through AI-powered knowledge generation.
- 🎓 **Deliver interactive educational experiences** with curriculum-friendly explanations for learners of all ages.
- 🔊 **Generate natural, expressive speech** using advanced AI-powered Text-to-Speech technology.
- 🎧 **Provide immersive AI Audio Guides**, narrating scenes, objects, products, museums, heritage & buildings , landmarks, and educational content with lifelike voice assistance for hands-free exploration.
- ♿ **Empower visually impaired and elderly users** through detailed scene descriptions, contextual awareness, and accessibility-first narration.
- 🎬 **Create cinematic AI storytelling experiences**, transforming static imagery into engaging multimedia narratives suitable for education, tourism, digital marketing, museums, and content creation.
- 💡 **Produce intelligent reports and contextual summaries** for research, innovation, and enterprise decision-making.

---

> **Picture Alive AI — Beyond Imagination**
>
> *Where Artificial Intelligence transforms every image into an extraordinary journey of discovery, knowledge, accessibility, and immersive storytelling.*
>
> 


------------------------------------------------------------------------------------------------------------------------------------------

## 🚀 Installation

This folder contains the complete source code for Picture Alive AI.

### GitHub Repository
https://github.com/Poppenspel-Advies/picture-alive-ai

### Clone Repository

```bash
git clone https://github.com/Poppenspel-Advies/picture-alive-ai.git
```

## Project Structure
```
PictureAliveAI/
├── backend/                  # FastAPI + Gemma 4 + Kokoro TTS
│   ├── main.py               # FastAPI entry point
│   ├── config.py             # Config & environment
│   ├── gemma_client.py       # Gemma 4 vision + text
│   ├── prompts.py            # Mode prompts
│   ├── routes.py             # SSE endpoints
│   ├── requirements.txt      # Dependencies
│   └── tests/                # Unit tests
├── asset/                 # confyUI generated UI
│   ├── css/
│   |── images/
|   |── images/
├── submission/               # Hackathon deliverables
│   ├── 1_project-profile/
│   ├── 2_source-code/
│   ├── 3_demo-video/
│   └── 4_supplementary/
└── README.md
└── index.html

```

-----------------------------------------------------------------------------------------------------------------------------------------

## How to Run

### Frontend

### Run locally

From the repository root:

```bash
python -m http.server 9000 --directory PictureAliveAI
```

Then open:

```text
http://127.0.0.1:9000/
```
-----------------------------------------------------------------------------------------------------------------------------------------

### Backend
```bash

cd PictureAliveAI/backend
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000

```

-----------------------------------------------------------------------------------------------------------------------------------------

## Picture Alive AI - Architecture Diagram

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/PictureAliveAI_Architecture_Diagram.png" width="90%">
</p>

------------------------------------------------------------------------------------------------------------------------------------------

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/modes/{mode}/analyze | Upload image (JPEG/PNG, max 10MB) -> Gemma 4 SSE stream |
| POST | /api/audio/generate?text= | Text -> Kokoro-82M WAV audio |
| POST | /api/modes/{mode}/generate | Upload image (JPEG/PNG, max 10MB) -> Gemma 4 SSE stream -> Text -> Kokoro-82M WAV audio 
| GET | /health | Health check |

-----------------------------------------------------------------------------------------------------------------------------------------

## Technology Stack

- **Frontend:** ComfyUI, React, Vite, Tailwind CSS, Typescript 
- **Backend:** Python 3.12, FastAPI
- **Vision + Text:** Gemma 4 (gemma-4-26b-a4b-it), via Google AI Studio
- **Text-to-Speech:** Kokoro-82M (Apache 2.0, local inference)
- **GPU:** AMD Radeon ROCm acceleration for TTS

-----------------------------------------------------------------------------------------------------------------------------------------

## Theme

The design follows the existing premium dark cinematic style with black, silver, and red accents, matching the current UI direction.

-----------------------------------------------------------------------------------------------------------------------------------------


# 📄 License

This project is licensed under the **MIT License**.

You are free to use, modify, distribute, and build upon this project in accordance with the terms of the MIT License.

Some third-party components used by Picture Alive AI retain their own respective licenses:

| Component | License |
|-----------|---------|
| Picture Alive AI | MIT License |
| Kokoro-82M | Apache License 2.0 |
| FastAPI | MIT License |
| Python | PSF License |
| ComfyUI | GPL-3.0 License |
| Hugging Face Libraries | Apache License 2.0 |
| Gemma 4 | Subject to Google's Gemma License Terms |

See the **LICENSE** file for complete details.

-----------------------------------------------------------------------------------------------------------------------------------------

## Picture Alive AI vs. Existing AI Platforms - The Comparative Analysis of Multimodal AI Platforms shown in the picture

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/CompetetiveStudyForPictureAliveAI.png" width="90%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------


# 🖼️ Application Showcase


# 🎬 Picture Alive AI — Product Demonstration

## Watch the Demo

<p align="center">

[![Picture Alive AI Demo](https://img.youtube.com/vi/_9gH0ES8FBw/maxresdefault.jpg)](https://www.youtube.com/watch?v=_9gH0ES8FBw)

### ▶️ https://www.youtube.com/watch?v=_9gH0ES8FBw

</p>

-----------------------------------------------------------------------------------------------------------------------------------------

# 🖼️ Application Walk Through

## 🏛️ Heritage & Tourism – AI Audio Guide

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/pictureAliveAI_HeritageMain.png" width="70%">
</p>

Transform every historical landmark, museum, monument, artwork, or cultural heritage site into an immersive AI-powered tour guide.

Picture Alive AI recognizes famous destinations and instantly generates rich historical narratives accompanied by lifelike multilingual audio narration, allowing visitors to explore history through intelligent storytelling.

### ✨ Features

- 🏛️ AI Landmark Recognition
- 🎧 Interactive AI Audio Guide
- 🌍 Historical & Cultural Storytelling
- 📍 GPS-Aware Location Intelligence
- 🗺️ Local Heritage Information
- 💰 Visitor Information & Entry Details
- ♿ Accessibility Narration
- 🌐 Cinematic Travel 
- 🎙️ Human-like Voice Narration
- 📖 Museum & Monument Knowledge Discovery

-----------------------------------------------------------------------------------------------------------------------------------------

## 🐅 Wildlife Intelligence

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/pictureAliveAI_DigitalMain.png" width="70%">
</p>

Discover the natural world through intelligent species recognition powered by advanced Computer Vision and Multimodal AI.

Upload a wildlife photograph and Picture Alive AI automatically identifies the species while generating detailed biological, ecological, and conservation insights with immersive AI narration.

### ✨ Features

- 🐅 Species Recognition
- 🧬 Scientific Name Identification
- 🌿 Habitat Analysis
- 🍽️ Food Habit Classification
- 🦴 Physical Characteristics
- 🧠 Behaviour Analysis
- 🌍 Geographic Distribution
- 📍 Current Location Mapping
- 📚 Evolution & Origin History
- 🦜 Species Family Classification
- 🎧 Wildlife Audio Narration
- 🌎 Conservation Awareness

-----------------------------------------------------------------------------------------------------------------------------------------

## ♿ Accessibility Intelligence

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/pictureAliveAI_AccessibilityMain.png" width="70%">
</p>

Designed with inclusivity at its core, Picture Alive AI empowers individuals with visual impairments, elderly users, and people with accessibility needs by transforming visual content into comprehensive spoken experiences.

Every image becomes an intelligent assistant capable of describing surroundings, identifying objects, reading text, recognizing emotions, and narrating contextual information in natural language.

### ✨ Features

- 👁️ Intelligent Scene Understanding
- 🗣️ AI-Powered Voice Assistance
- 🎧 Real-Time Audio Narration
- 📖 OCR Text Reading
- 😊 Facial Emotion Recognition
- 🚶 Environmental Awareness
- 🪑 Indoor & Outdoor Navigation Support
- 🚦 Hazard & Obstacle Detection
- 🏥 Medical Assistance Scenarios
- 🛒 Everyday Shopping Assistance
- 🎓 Educational Accessibility

-----------------------------------------------------------------------------------------------------------------------------------------

# 🌐 Digital World Intelligence

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/pictureAliveAI_Digital4.png" width="70%">
</p>

Analyze products, engineering systems, industrial equipment, consumer electronics, aerospace hardware, scientific instruments, and innovative technologies using AI-powered product intelligence.

Picture Alive AI transforms complex technical products into simplified knowledge through intelligent analysis, engineering explanations, architecture visualization, and natural voice narration.

### ✨ Features

- 📱 Product Recognition
- ⚙️ Engineering Analysis
- 🏭 Industrial Equipment Intelligence
- 📊 Product Specifications
- 💡 Innovation Analysis
- 🏗️ Product Architecture
- 💰 Cost Effectiveness Analysis
- 📈 Market Potential Prediction
- 📢 AI Social Media Content Generation
- 🎤 AI Product Narration
- 🚀 Future Technology Insights
- 🧠 Intelligent Technical Reports

-----------------------------------------------------------------------------------------------------------------------------------------

# 🎭 Content Creation Studio

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/pictureAliveAI_Content1.png" width="70%">
</p>

Picture Alive AI transforms static images into cinematic storytelling experiences, immersive podcasts, educational narratives, and creative multimedia content.

Using multimodal AI reasoning, the platform generates emotionally engaging stories, realistic conversations, and professional-quality narration suitable for entertainment, education, marketing, museums, and digital publishing.

### ✨ Features

- 🎬 AI Storytelling
- 📖 Creative Narrative Generation
- 🎭 Character Conversations
- 🎤 Podcast Generation
- 🎨 Artwork Interpretation
- 🏰 Historical Reimagination
- 🎞️ Cinematic Narration
- 😊 Emotion-Aware Storytelling
- 📚 Educational Story Creation
- 🌍 Cultural Storytelling
- 🔊 Human-like Voice Narration
- ✨ Creative Content Generation

--------------------------------------------------------------------------------------------------------------------------------------

# 🖥️ Picture Alive AI — Premium User Interface

Picture Alive AI delivers a **luxury cinematic multimodal AI workspace** that transforms a traditional AI application into an immersive interactive platform. Every validation and action trigger in Picture Alive AI comes with a Toast message and some of them has loud voice  system notification to user - for example for successfully responses, errored out response scenarios with error message, welcome message, pro Upgrade features and some UI Validations too.

Designed with a **black, silver, red, and neon holographic theme**, the interface emphasizes usability, accessibility, and premium user experience while providing real-time AI-generated multimedia outputs. 

---

# ✨ Dashboard Overview

The application is organized into three intelligent workspaces.

```
┌──────────────────────────────────────────────────────────┐
│ Left Navigation │ AI Workspace │ AI Actions │
└──────────────────────────────────────────────────────────┘
```

- Intelligent Navigation
- AI Upload Workspace
- Multimodal Output
- AI Generation Panel
- Creation History
- Download Center
- Prompt Editor
- Audio Controls
- AI Lab

---

# 📸 User Interface Showcase

## 🏠 Main Dashboard

The dashboard has a system define welcome loud message for the user to inform what is "Picture Alive AI".


<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20133945.png" width="95%">
</p>

------------------------------------------------------------------------------------------------------------------------------------------

## 🎓 Education

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20135743.png" width="95%">
</p>

----------------------------------------------------------------------------------------------------------------------------------------

## ♿ Accessibility

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20141042.png" width="95%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

## 🏛 Heritage & Tourism

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20135603.png" width="95%">
</p>

------------------------------------------------------------------------------------------------------------------------------------------

## 🌐 Digital World

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20143201.png" width="95%">
</p>

------------------------------------------------------------------------------------------------------------------------------------------

## 🎨 Content Creation

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20144146.png" width="95%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

## 🤖 AI Generated Response

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20185517.png" width="95%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

# 📂 Left Navigation Panel

The navigation provides quick access to every multimodal AI capability.

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20145858.png" width="25%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------


### 🎓 Education

Generate

- Interactive learning
- AI teacher explanations
- Educational storytelling
- Student-friendly content
- Visual learning

---

### ♿ Accessibility

Designed specifically for visually impaired users.

Features include

- Audio narration
- Scene understanding
- Object recognition
- Emotion detection
- Voice guidance
- Screen-reader friendly descriptions

---

### 🏛 Heritage & Tourism

Transform landmarks into intelligent museum experiences.

Generate

- Historical analysis
- Cultural insights
- Tourist narration
- Audio guides
- Architecture explanations
- Interactive storytelling

---

### 🌐 Digital World

Recognize real-world products and technology.

Generate

- Product intelligence
- Engineering analysis
- Technical specifications
- Market insights
- Innovation summaries
- AI recommendations

---

### 🎨 Content Creation

Turn any image into immersive multimedia.

Generate

- Stories
- AI podcasts
- Character conversations
- Emotional narration
- Script generation
- Social media content

---

# 📤 Image Upload Workspace

The center workspace allows users to upload images using drag-and-drop or the upload button. Once the image will be uploaded on click of "Generate Response" button the uploaded user image will be shown in main panel view and user will get a message that the response is getting generated and once it will be ready, system has a loud voice to inform user that the "Response got generated successfully" , user can preview the response in main view.

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20134720.png" width="60%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

Supported formats

- JPG
- PNG
- WEBP

Maximum upload size

- 20 MB

After upload, the image is processed by the multimodal AI engine.

-----------------------------------------------------------------------------------------------------------------------------------------

# 🤖 Multimodal Output Panel

Users can generate multiple outputs from a single image.

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20145200.png" width="60%">
</p>

---------------------------------------------------------------------------------------------------------------------------------------


Available modes include

🖼️ Image Analysis

🎥 Video Generation

🔊 Audio Narration

📖 Story Generation

🎙️ Voice Over

Each output is generated from the same uploaded image without requiring additional prompts.

---

# 🎧 Built-in Audio Preview

The interface includes a built-in AI audio player featuring

- Play/Pause controls
- Progress timeline
- Download audio
- Language selection
- AI narration preview

Perfect for

- Museums
- Education
- Tourism
- Accessibility
- Podcasts

---

# 🧠 Picture Alive AI Lab

The secure AI processing environment displays

- AI Status
- Generation Pipeline
- Secure Client Engine
- Processing Statistics
- Rendering Information
- Active AI Modules

------------------------------------------------------------------------------------------------------------------------------------------

# ⚙️ AI Action Panel

The right sidebar provides productivity tools for generated content.

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20145658.png" width="25%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

Features include

⬇️ Download Results (4K)

🔗 Share

✏️ Modify Prompt

🔄 Regenerate

🎞 Convert Output Format

These controls allow users to instantly customize AI-generated content.

---

# 📑 Creation Details

<p align="center">
<img src="https://github.com/Poppenspel-Advies/picture-alive-ai/blob/main/PictureAliveAI/assets/images/Screenshot%202026-08-04%20145757.png" width="20%">
</p>

-----------------------------------------------------------------------------------------------------------------------------------------

Displays

- Prompt
- AI Mode
- Processing Information
- Output Metadata
- AI Generation Status

---

# 🎯 AI Response Screen

Once generation is complete, the application presents a premium AI report that includes

- High-resolution image
- AI-generated narration
- Storytelling
- Character conversations
- Historical information
- Educational insights
- Product analysis
- Emotional understanding
- Practical applications
- Interactive multimedia panels

Every generated report follows a cinematic magazine-style layout.

---

# 🌍 Application Experiences

The UI dynamically changes based on the selected mode.

| AI Experience | Dynamic Interface |
|---------------|-------------------|
| 🎓 Education | Interactive classroom and AI tutor experience |
| ♿ Accessibility | Voice-first interface with descriptive narration |
| 🏛 Heritage & Tourism | Museum guide and historical storytelling |
| 🌐 Digital World | Product intelligence dashboard |
| 🎨 Content Creation | AI storytelling studio with podcast generation |

---

# 🎨 Premium Design Language

The UI follows a premium design system featuring

- Glassmorphism
- Neon gradients
- Black luxury theme
- Red & silver accents
- Animated AI panels
- Rounded premium cards
- Responsive layouts
- Holographic highlights
- Cinematic typography
- Interactive animations

---

# ⚡ Complete User Workflow

```text
Open Picture Alive AI

        │

        ▼

Choose AI Experience

        │

        ▼

Upload Image

        │

        ▼

Gemma 4 Vision Analysis

        │

        ▼

AI Understanding

        │

 ┌───────────────┬───────────────┬──────────────┐

 ▼               ▼               ▼

Story        Audio Guide      Product Report

 ▼               ▼               ▼

Podcast      Narration      Educational Guide

        │

        ▼

Download • Share • Regenerate
```

---

# 💎 User Experience Highlights

✔ Premium Cinematic Dashboard

✔ Responsive Design

✔ Real-time AI Generation

✔ Multimodal AI Workspace

✔ Audio-first Accessibility

✔ AI Storytelling

✔ Interactive Heritage Experiences

✔ Product Intelligence

✔ AI Podcast Creation

✔ Educational Content Generation

✔ One Image → Multiple AI Outputs

✔ Enterprise-grade User Experience


---------------------------------------------------------------------------------------------------------------------------------------



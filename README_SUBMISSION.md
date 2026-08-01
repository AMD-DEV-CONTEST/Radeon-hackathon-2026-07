# Aegis Analytics AI System

**AMD AI DevMaster Hackathon 2026**

## Track
**Track 2 – Development & Local Deployment of Private AI Agents**

## Participant
**Udit Rajput**

---

# Project Overview

Aegis Analytics AI System is an AI-powered analytics platform that enables users to upload, process, analyze, and visualize data through an intuitive web interface. The application leverages modern AI capabilities to generate meaningful insights, automate report generation, and simplify data-driven decision-making.

The system is built with a FastAPI backend and a React frontend, providing a scalable and responsive architecture suitable for local deployment.

---

# Problem Statement

Organizations and individuals often struggle to extract actionable insights from large datasets without extensive technical expertise. Existing analytics tools can be complex, expensive, or require significant manual effort.

Aegis Analytics AI System addresses this challenge by providing an AI-assisted analytics platform that simplifies data analysis, visualization, and reporting.

---

# Application Scenarios

- Business Intelligence & Reporting
- Sales & Marketing Analytics
- Educational Data Analysis
- Research Projects
- Personal Data Exploration
- AI-assisted Decision Support

---

# Core Capabilities

- AI-powered analytics
- Automated insight generation
- Interactive dashboards
- Data visualization
- Report generation
- REST API services
- Modern responsive UI
- Easy local deployment

---

# System Architecture

```
                +--------------------+
                |     React Frontend |
                +----------+---------+
                           |
                     REST API Calls
                           |
                +----------v---------+
                |   FastAPI Backend  |
                +----------+---------+
                           |
        +------------------+------------------+
        |                                     |
 AI Processing Engine                Data Processing
        |                                     |
        +------------------+------------------+
                           |
                     Analytics Results
                           |
                  Dashboard & Reports
```

---

# Technology Stack

## Backend

- Python
- FastAPI

## Frontend

- React
- JavaScript
- HTML
- CSS

## Tools

- Git
- GitHub
- REST APIs

---

# Local Deployment

## Requirements

- Python 3.10+
- Node.js 18+
- npm
- pip

---

## Backend Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

---

# Project Repository

GitHub Repository

https://github.com/Uditrajput09/aegis-analytics-ai-system

---

# Demo Video

Demo Video Link

(Add your YouTube or Google Drive link here)

---

# AMD Radeon GPU / ROCm Optimization

This project is designed to be compatible with AI frameworks that support AMD Radeon GPUs through ROCm. The current implementation focuses on local deployment and modular AI integration.

Future enhancements include:

- Native ROCm acceleration
- Optimized inference pipeline
- GPU-based model execution
- Performance benchmarking on AMD Radeon GPUs

---

# Project Deliverables

✅ Project Specification Document (PDF)

✅ Complete Source Code

✅ README Documentation

✅ Demo Video

✅ Presentation (PPT)

---

# Future Improvements

- Multi-model AI support
- Advanced analytics dashboard
- Real-time data streaming
- Collaborative analytics
- ROCm-native optimization
- Enhanced visualization modules

---

# Repository Structure

```
Aegis-Analytics-AI-System/
│
├── backend/
├── frontend/
├── README.md
├── requirements.txt
├── Project_Specification.pdf
└── Presentation.pptx
```

---

# License

This project was developed for submission to the **AMD AI DevMaster Hackathon 2026**.

---

# Contact

**Udit Rajput**

GitHub:
https://github.com/Uditrajput09

LinkedIn:
https://www.linkedin.com/in/udit-rajput-0115403a/
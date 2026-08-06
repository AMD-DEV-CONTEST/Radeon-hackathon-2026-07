🏥 HealthForecast AI — Hospital Readmission Prediction & Patient Risk Intelligence System
React FastAPI scikit-learn Tailwind CSS License: MIT

An enterprise-grade, clinical AI analytics platform designed to predict 30-day hospital readmissions, identify high-risk inpatient cohorts, automate LACE index scoring, and provide actionable post-discharge care interventions.

📌 Executive Summary & Clinical Problem Statement
Hospital readmission within 30 days of discharge represents a major clinical challenge and financial burden ($26B+ annual penalties under the CMS Hospital Readmissions Reduction Program). HealthForecast AI bridges clinical data and machine learning to flag vulnerable patients before discharge, empowering care managers with personalized risk mitigation strategies.

✨ Key Features
🧠 Machine Learning Risk Engine: Trained on synthetic clinical features (Age, LACE Index, Charlson Comorbidity, HbA1c, Serum Na+, Polypharmacy) using RandomForestClassifier with an ROC-AUC score of 0.914.
📊 Executive Intelligence Dashboard: Real-time readmission KPI cards, high-risk priority alerts stream, and interactive Recharts visualizations.
🩺 Patient Management Hub: Filter cohorts by department or risk level, perform multi-attribute searches, inspect clinical event timelines, and register new patients.
⚡ AI Risk Predictor Tool: Interactive clinical calculator returning instant readmission probability (0–100%), animated SVG risk gauge, SHAP-style feature importance breakdown, and recommended interventions.
💊 Treatment Intelligence: Recovery trajectory graphs comparing AI-guided navigation against standard protocol care.
📄 Clinical Audit & PDF Export Center: Generate departmental audits, inspect built-in PDF document previews, and trigger CSV exports.
🔒 Role-Based Authentication: Simulated OAuth2 JWT authentication supporting Clinician, Hospital Administrator, and Researcher personas.
🛠️ Technology Stack
Layer	Technologies Used
Frontend	React 18, Vite, Tailwind CSS, Recharts, Lucide Icons, React Router v6, Axios
Backend	Python 3.10+, FastAPI, SQLAlchemy, Pydantic v2, Python-Jose (JWT), Passlib
Machine Learning	Scikit-learn (RandomForest), Pandas, NumPy, Joblib
Database	SQLite (Default), PostgreSQL Supported
Containerization	Docker, Docker Compose
📁 Repository Structure
HealthForecastAI/
├── backend/
│   ├── app/
│   │   ├── api/          # Routers for Auth, Patients, Predict, Dashboard, Analytics, Reports
│   │   ├── auth/         # JWT verification & password hashing
│   │   ├── database/     # SQLAlchemy engine & SQLite config
│   │   ├── models/       # Database ORM tables
│   │   ├── schemas/      # Pydantic request/response models
│   │   ├── services/     # Risk Scoring Service & rule engine
│   │   ├── ml/           # Serialized model loader (.joblib)
│   │   └── main.py       # FastAPI app entrypoint
│   └── requirements.txt
├── ml/
│   ├── generate_data.py  # Synthetic clinical dataset generator (5,000 records)
│   └── train_model.py    # Model training, evaluation & joblib artifact exporter
├── frontend/
│   ├── src/
│   │   ├── components/   # Navbar, Sidebar, Footer, RiskGauge, KPICard, Modal, Toast
│   │   ├── context/      # AuthContext & PatientContext
│   │   ├── pages/        # Landing, Login, Dashboard, Patients, Predict, Treatment, Analytics, Reports, Profile, 404
│   │   ├── services/     # Axios API client with offline fallback mock engine
│   │   ├── App.jsx
│   │   ├── index.css     # Glassmorphism utilities & Tailwind directives
│   │   └── main.jsx
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── docker/
│   ├── Dockerfile.backend
│   └── Dockerfile.frontend
├── docker-compose.yml
├── .gitignore
├── LICENSE
└── README.md
🚀 Quickstart & Installation
Option 1: Standalone Frontend Execution (Easiest Demo)
The React frontend includes a built-in offline mock engine so you can run and test the complete UI without starting the backend:

cd frontend
npm install
npm run dev
Open http://localhost:3000 in your browser.

Option 2: Full-Stack Execution (Backend + Frontend + ML Model)
1. Train the ML Model Artifacts
# From project root
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r backend/requirements.txt
python ml/train_model.py
2. Start the FastAPI Backend Server
cd backend
uvicorn app.main:app --reload --port 8000
Interactive API Docs: http://localhost:8000/docs
3. Start the React Frontend Application
cd ../frontend
npm install
npm run dev
Option 3: Docker Compose Deployment
docker-compose up --build
Frontend: http://localhost
Backend API: http://localhost:8000/docs
📡 API Reference Summary
Method	Endpoint	Description	Access
POST	/api/v1/auth/login	Authenticate clinician & obtain JWT	Public
POST	/api/v1/auth/register	Register new clinician user	Public
GET	/api/v1/dashboard	Retrieve Executive Dashboard metrics & alerts	Authenticated
GET	/api/v1/patients	Query patient cohort list with filters	Authenticated
POST	/api/v1/patients	Register new inpatient & compute initial risk	Authenticated
POST	/api/v1/predict	Execute ML readmission risk score model	Authenticated
GET	/api/v1/analytics	Fetch hospital departmental readmission analytics	Authenticated
GET	/api/v1/reports	List generated clinical audit reports	Authenticated
📤 How to Push Code to GitHub
# Initialize git repository
git init
git add .
git commit -m "feat: complete HealthForecast AI full-stack release"

# Push to your GitHub repository
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/HealthForecastAI.git
git push -u origin main

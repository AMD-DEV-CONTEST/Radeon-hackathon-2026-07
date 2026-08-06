# StudyTrack

StudyTrack is an AI-powered web application that helps students improve academic performance and assess career readiness through intelligent quizzes, coding assessments, and personalized skill-gap analysis.

# Live Demo

https://ai-adaptive-learning-ten.vercel.app/

# Features

# Academic Module

- Generate AI-based quizzes from a subject and topic
- Upload PDF or TXT study material or paste notes
- Generate multiple-choice, theory, and short-answer questions
- Automatic answer evaluation
- Weak-area analysis
- Personalized study recommendations
- Academic performance reports

# Career Module

- Identify skills required for a target career
- AI-generated theory and coding assessments
- Integrated Monaco Python code editor
- Execute Python code securely with time and output limits
- Career readiness scoring
- Skill-gap analysis
- Personalized learning roadmap

# Technology Stack

# Frontend

- React
- Vite
- React Router
- Axios
- Recharts
- Monaco Editor
- Framer Motion

# Backend

- Flask
- Flask-JWT-Extended
- Flask-CORS
- SQLite
- bcrypt
- PyMuPDF

# AI Services

- Groq (Llama 3.3 70B Versatile)
- Google Gemini 1.5 Flash (Fallback)

# Installation

Clone the repository:

```bash
git clone https://github.com/RR-Priyadharshini/AI-adaptiveLearning.git
cd AI-adaptiveLearning
```

# Backend

```bash
cd backend
pip install -r requirements.txt
python app.py
```

# Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend will run at:

```
http://localhost:5173
```

The backend will run at:

```
http://localhost:5000
```

# Environment Variables

Create a `.env` file inside the `backend` directory.

```env
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
JWT_SECRET_KEY=your_jwt_secret
```

# Project Structure

```
AI-adaptiveLearning/
│
├── backend/
│   ├── app.py
│   ├── academic_module.py
│   ├── career_module.py
│   ├── auth_module.py
│   ├── ai_service.py
│   ├── database.py
│   └── code_runner.py
│
├── frontend/
│   └── src/
│       ├── components/
│       ├── context/
│       └── pages/
│
└── start.bat
```

# Author

Priyadharshini R

GitHub: https://github.com/RR-Priyadharshini

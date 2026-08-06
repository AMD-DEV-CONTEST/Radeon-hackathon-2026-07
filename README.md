# 🎓 EduCopilot — Autonomous Virtual TA & Accreditation Engine

An AI-powered Teaching Assistant that automates the full life cycle of higher-education courses using any OpenAI-compatible LLM endpoint.

## Quick Start

```powershell
# 1. Configure an OpenAI-compatible endpoint (defaults to local Ollama)
$env:OPENAI_BASE_URL = "http://localhost:11434/v1"
$env:OPENAI_API_KEY = "ollama"
$env:OPENAI_MODEL = "gemma4"

# 2. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Run the web app
python webapp.py
```

Open **http://localhost:7860**

## Easy Local Docker Setup

For the shortest AMD ROCm-oriented setup, see [QUICKSTART.md](QUICKSTART.md).
For the full AMD hackathon specification, architecture, feature documentation,
demo plan, and limitations, see [HACKATHON_SPECIFICATION.md](HACKATHON_SPECIFICATION.md).

Docker Compose runs EduCopilot with Flask's built-in web server. It stores the
SQLite database and Chroma data in the persistent `educopilot_data` volume.
This is intended for local deployment and testing, not cloud production use.

1. Start your OpenAI-compatible endpoint. For local Ollama, install it and make
sure the model is available:

```powershell
ollama pull gemma4
```

2. Build and start EduCopilot:

```powershell
docker compose up --build -d
```

3. Open **http://localhost:7860** in your browser. View logs with:

```powershell
docker compose logs -f educopilot
```

The default Compose configuration connects to Ollama running on the same
computer at `http://host.docker.internal:11434/v1`. For another provider,
create a `.env` file beside `docker-compose.yml`:

```dotenv
OPENAI_BASE_URL=https://your-provider.example.com/v1
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
```

The endpoint must expose the OpenAI Chat Completions API. To stop the app, run:

```powershell
docker compose down
```

The existing local `educopilot.db` is intentionally excluded from the image;
copy it into the `educopilot_data` volume or use a bind mount if you need its
data in the container.

## Features

| Feature | Description |
|---------|-------------|
| **📚 Course Dashboard** | Visual card-based overview of all courses — click to open |
| **➕ Add Course** | Paste syllabus, COs, materials + # of classes + instructions → AI generates class-wise plan |
| **📊 Progress Tracking** | Log each class with topics, comments, student questions, pace notes |
| **📝 Content Generation** | Auto-generate slides, handouts, and teacher notes — uses previous class feedback |
| **✍️ Assignment Evaluation** | Paste student answers → AI evaluates against COs, assigns marks, saves to profile |
| **👥 Student Profiling** | Cohort analysis (Remedial/Average/Advanced) + AI Class Intelligence report |
| **📝 Exam Generator** | Adaptive exams by cohort + CO, aligned to Bloom's Taxonomy levels |
| **📋 Accreditation** | One-click NBA/ABET course file with CO attainment and improvement plans |

## Tech Stack

- **Backend:** Python 3.11+, Flask
- **LLM:** Local Ollama + Gemma 4 (OpenAI-compatible API)
- **Data Validation:** Pydantic v2
- **Storage:** SQLite3
- **Frontend:** Bootstrap 5, Jinja2 templates
- **AI Agents:** LangGraph / LangChain

## Project Structure

```
AMDAI-EduCopilot/
├── webapp.py              # ← Flask web application (main entry point)
├── config.py              # Endpoint config & system prompts
├── database.py            # SQLite setup and all queries
├── schemas.py             # Pydantic data models
├── llm_service.py         # Ollama API bridge
├── agents/
│   ├── planner_agent.py   # Syllabus parsing & lesson planning
│   ├── tracking_agent.py  # Class progress & catch-up plans
│   ├── analytics_agent.py # Student profiling & adaptive exams
│   ├── content_agent.py   # Slides, handouts, teacher notes
│   ├── eval_agent.py      # Assignment evaluation
│   └── nba_agent.py       # Accreditation reports
├── templates/
│   ├── base.html          # Base layout (navbar, flash messages)
│   ├── dashboard.html     # Course cards grid
│   ├── add_course.html    # Course creation form
│   ├── add_course_result.html
│   ├── course_detail.html # Tabbed course view
│   ├── log_class.html     # Class logging form
│   ├── content.html       # Content generation
│   ├── evaluate.html      # Assignment evaluation
│   ├── profiling.html     # Student profiling & CSV import
│   ├── exams.html         # Exam generator
│   └── accreditation.html # NBA/ABET report
├── .venv/                 # Python virtual environment
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── QUICKSTART.md
├── HACKATHON_SPECIFICATION.md
└── README.md
```

## License

All rights reserved.

# IndusMind AI Setup Guide

## Install

1. Git for Windows
2. IntelliJ IDEA Community Edition
3. Eclipse Temurin JDK 21
4. Maven 3.9+
5. Node.js LTS
6. Python 3.11 or 3.12
7. PostgreSQL 16+ and pgAdmin for the production profile
8. Tesseract OCR only if scanned-PDF OCR is required
9. OBS Studio for recording the demo

During Python installation, enable **Add Python to PATH**.

## IntelliJ configuration

1. Open the repository.
2. Import `backend/pom.xml` as a Maven project.
3. Set Project SDK to Java 21 or newer.
4. Run `IndusMindApplication`.
5. Add `--spring.profiles.active=demo` for zero-setup local mode.

The frontend and AI service are best run from IntelliJ's terminal or VS Code.

## Manual startup

Terminal 1:

```powershell
cd ai-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Terminal 2:

```powershell
cd backend
mvn spring-boot:run -Dspring-boot.run.profiles=demo
```

Terminal 3:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Then visit `http://localhost:5173`.

## Ports

- React: `5173`
- Spring Boot: `8081`
- FastAPI: `8000`
- PostgreSQL: `5432`


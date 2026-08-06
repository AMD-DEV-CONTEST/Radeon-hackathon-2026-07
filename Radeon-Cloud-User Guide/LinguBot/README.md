# LinguaBot - AI-Powered Language Learning Platform

LinguaBot is an enterprise-grade, full-stack language learning portal. It enables users to practice target languages via an AI chatbot, audit grammar with mistake analyses, translate snippets into 100+ languages, and test themselves via custom AI-generated quizzes. A dashboard visualizes performance metrics, streaks, charts, achievements, and claims verification certificates upon course completion.

---

## Technical Stack

* **Frontend**: React 18, React Router v6, Tailwind CSS, Axios, Chart.js, React Icons.
* **Backend**: Java 17, Spring Boot 3.3.2, Spring Security, JWT (HMAC-SHA256), Spring Data MongoDB, Lombok, Maven.
* **Database**: MongoDB Atlas.
* **AI Provider**: Google Gemini API (model `gemini-1.5-flash`).

---

## Folder Directory Structure

```
├── backend/
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/java/com/linguabot/
│       ├── LinguabotApplication.java
│       ├── config/           # Security, CORS, Auditing configuration
│       ├── controller/       # REST Controller endpoints
│       ├── service/          # AI connection services and business logic
│       ├── repository/       # Database access layers
│       ├── model/            # Document entities
│       ├── dto/              # Transfer payloads
│       ├── security/         # JWT filter and entrypoints
│       └── exception/        # Exception handlers
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── vercel.json
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── index.css
│       ├── context/          # Session and Theme contexts
│       ├── components/       # Sidebars, Headers, and Protected Routes
│       ├── pages/            # Login, Chat, Grammar, Translate, Quiz, Progress, Admin
│       └── utils/            # Markdown utilities
├── docker-compose.yml
├── .github/workflows/
│   └── deploy.yml
└── README.md
```

---

## Environment Variables

Ensure these keys are populated in your runtime configurations:

| Variable | Location | Description |
|---|---|---|
| `MONGODB_URI` | Backend | Connection URL for MongoDB (e.g. Atlas connection string) |
| `JWT_SECRET` | Backend | HMAC-SHA256 Base64 Secret Key for token signatures |
| `GEMINI_API_KEY` | Backend | Google Generative Language API Key for AI operations |

---

## Local Development Setup

### Prerequisite Checklist
1. **Java Runtime**: JDK 17 installed.
2. **Node Environment**: Node.js 18+ and NPM installed.
3. **Database**: Local MongoDB server or MongoDB Atlas cluster.

### Step 1: Spin Up Backend Services
1. Navigate to `/backend`:
   ```bash
   cd backend
   ```
2. Build the Maven target wrapper:
   ```bash
   mvn clean install -DskipTests
   ```
3. Boot the application:
   ```bash
   mvn spring-boot:run
   ```
   *The server boots on port `8080` (context path `/api`).*

### Step 2: Spin Up Frontend Client
1. Navigate to `/frontend`:
   ```bash
   cd ../frontend
   ```
2. Download packages:
   ```bash
   npm install
   ```
3. Boot the development dev server:
   ```bash
   npm run dev
   ```
   *The client boots on port `3000` (proxies `/api` requests to backend).*

---

## Running with Docker Compose

To build and run all platform services (MongoDB database container, Java backend, and compiled Nginx React server) locally in a unified docker network:

1. In the root workspace directory, run:
   ```bash
   docker compose up --build
   ```
2. Open your browser and navigate to: `http://localhost:3000`

---

## Production Cloud Deployments

### 1. Database (MongoDB Atlas)
1. Register on [MongoDB Atlas](https://www.mongodb.com/cloud/atlas).
2. Deploy a free cluster and select **Connect via Driver**.
3. Copy the URI string and replace `<password>` with your database user password. Add this string as `MONGODB_URI` in the backend environment settings.

### 2. Backend (Railway or Render)
1. Create a service and link your Repository.
2. Target the `/backend` folder. Specify the build command as `mvn clean package -DskipTests` and start command as `java -jar target/linguabot-0.0.1-SNAPSHOT.jar`.
3. Add environmental keys: `MONGODB_URI`, `JWT_SECRET` (Base64 string), and `GEMINI_API_KEY`.

### 3. Frontend (Vercel)
1. Deploy new project in [Vercel](https://vercel.com) linking the repository.
2. Select the `frontend` folder as the root directory.
3. Vercel automatically reads `vercel.json` for path overrides and handles deployment. Edit `vercel.json` destination properties to point to your deployed Railway/Render backend URL.

# AiAssistant — Complete Project Documentation

> **An AI-powered business automation platform** with document generation, voice agents, WhatsApp chat, analytics, and database management.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [Features & Modules](#5-features--modules)
6. [API Reference](#6-api-reference)
7. [Database Schema](#7-database-schema)
8. [Authentication & Security](#8-authentication--security)
9. [Installation & Setup](#9-installation--setup)
10. [Development Guide](#10-development-guide)
11. [Deployment](#11-deployment)
12. [Contributing](#12-contributing)

---

## 1. Project Overview

### 1.1 What is AiAssistant?

AiAssistant is a full-stack, AI-powered business automation platform that enables businesses to:

- **Generate professional documents** (PDF, DOCX, XLSX, CSV, HTML) using AI
- **Deploy intelligent voice agents** that handle phone calls with natural conversation
- **Automate WhatsApp messaging** with AI-driven customer interactions
- **Analyze business data** through an AI analytics agent connected to external databases
- **Manage external databases** (PostgreSQL, MongoDB, Google Sheets, Supabase) via natural language
- **Create project profiles** with HTML, PDF, and PPT outputs

### 1.2 Core Philosophy

The platform is designed to be **business-type agnostic** — it works for ANY business type (retail, healthcare, real estate, education, etc.) by dynamically adapting to the business description provided during setup. No hardcoded business logic.

### 1.3 Target Users

- Small to medium businesses needing AI-powered customer engagement
- Developers wanting a ready-made AI automation backend
- Hackathon projects requiring a full-stack AI platform

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Dashboard│ │ Document │ │  Voice   │ │   WhatsApp    │  │
│  │   Page   │ │ Generator│ │  Agent   │ │     Chat      │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Analytics│ │ Database │ │ Settings │ │Project Profile│  │
│  │   Page   │ │  Agent   │ │   Page   │ │     Page      │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / WebSocket / Socket.IO
┌──────────────────────▼──────────────────────────────────────┐
│                   Backend (Express.js)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │   Auth   │ │ Document │ │  Voice   │ │   WhatsApp    │  │
│  │    JWT   │ │Generator │ │  Agent   │ │     Agent     │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │Database  │ │Analytics │ │ Settings │ │Project Profile│  │
│  │ Agent    │ │  Agent   │ │ Manager  │ │  Generator    │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└──────┬──────────────────────┬──────────────────┬────────────┘
       │                      │                  │
       ▼                      ▼                  ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│  PostgreSQL  │   │ External DBs     │   │    Redis     │
│  (Sequelize) │   │ (PG/Mongo/Sheets)│   │   (Cache)    │
└──────────────┘   └──────────────────┘   └──────────────┘
```

### 2.1 Data Flow

1. **User** interacts with the React frontend
2. **Frontend** sends requests via Axios HTTP client or Socket.IO for real-time streaming
3. **Backend** processes requests through Express.js controllers
4. **AI Layer** uses AMD Radion Cloud AI for all LLM operations
5. **Database Layer** uses Sequelize ORM for PostgreSQL and direct drivers for external DBs
6. **Twilio** handles voice calls and WhatsApp messaging via webhooks

---

## 3. Technology Stack

### 3.1 Frontend

| Technology | Version | Purpose |
|---|---|---|
| React | 19.x | UI framework |
| TypeScript | 5.x | Type safety |
| Vite | 6.x | Build tool & dev server |
| Tailwind CSS | 4.x | Utility-first styling |
| shadcn/ui | Latest | UI component library |
| TanStack Query | 5.x | Server state management |
| Redux Toolkit | 2.x | Client state management |
| React Router | 7.x | Client-side routing |
| Lucide React | Latest | Icon library |
| Socket.IO Client | 4.x | Real-time communication |
| jsPDF | 4.x | Client-side PDF generation |
| html2canvas | 1.x | HTML to canvas rendering |
| Fortune Sheet | 1.x | Spreadsheet viewer |
| Univer | 0.25.x | Document viewer |

### 3.2 Backend

| Technology | Version | Purpose |
|---|---|---|
| Node.js | 20+ | Runtime |
| Express | 5.x | Web framework |
| Sequelize | 6.x | PostgreSQL ORM |
| PostgreSQL | 15+ | Primary database |
| Socket.IO | 4.x | Real-time WebSocket server |
| JWT (jsonwebtoken) | 9.x | Authentication |
| bcryptjs | 3.x | Password hashing |
| Passport.js | 0.7.x | Google OAuth |
| Multer | 2.x | File uploads |
| Helmet | 8.x | Security headers |
| Redis (ioredis) | 5.x | Caching & session store |
| Twilio | 6.x | Voice & WhatsApp API |
| Nodemailer | 9.x | Email sending |
| pdfkit | 0.19.x | Server-side PDF generation |
| pptxgenjs | 3.x | PPT presentation generation |
| exceljs | 3.x | XLSX/CSV generation |
| docx | 8.x | DOCX generation |
| kokoro-js | 1.x | Local TTS (text-to-speech) |

### 3.3 AI & LLM

| Service | Model | Usage |
|---|---|---|
| AMD Radion Cloud AI | DeepSeek V4 Pro/Flash | All LLM operations |
| LangChain | Core + Community | LLM orchestration, prompt templates |
| Kokoro TTS | Kokoro-82M | Local voice synthesis |

---

## 4. Project Structure

```
AiAssistant/
├── README.md
├── DOCUMENTATION.md          ← This file
├── backend/
│   ├── package.json
│   ├── server.js             ← Express server entry point
│   ├── config/
│   │   ├── sequelize.js      ← PostgreSQL/Sequelize connection
│   │   └── upload.js         ← File upload configuration
│   ├── controller/
│   │   ├── AuthController.js       ← Login/logout
│   │   ├── RegisterController.js   ← Registration & email verification
│   │   ├── UserController.js       ← User profile CRUD
│   │   ├── LogoController.js       ← Brand logo management
│   │   ├── SettingsController.js   ← User settings CRUD
│   │   ├── generator.js            ← AI document generation (LLM)
│   │   ├── DatabaseController.js   ← External DB agent with guardrails
│   │   ├── AnalyticsController.js  ← AI analytics agent
│   │   ├── voiceAgent.js           ← Twilio voice call handler
│   │   ├── whatsappAgent.js        ← Twilio/Meta WhatsApp handler
│   │   ├── HistoryController.js    ← Activity history
│   │   └── ProjectProfileController.js ← Project profile generator
│   ├── middleware/
│   │   └── authmiddleware.js  ← JWT authentication middleware
│   ├── model/
│   │   ├── register.js        ← User model
│   │   ├── business.js        ← Business model
│   │   ├── logo.js            ← Logo model
│   │   ├── settings.js        ← Settings model
│   │   ├── history.js         ← History model
│   │   └── agent_memory.js    ← AI agent conversation memory
│   ├── router/
│   │   └── router.js          ← Route definitions
│   ├── utils/
│   │   ├── jwt.js             ← JWT token utilities
│   │   ├── gmail.js           ← Nodemailer email sender
│   │   ├── tts.js             ← Kokoro TTS service
│   │   └── businessSchemas.js ← DB schema templates per business type
│   └── uploads/
│       └── tts/               ← Generated TTS audio files
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx           ← React entry point
│       ├── App.tsx            ← Router configuration
│       ├── api/
│       │   ├── axios.ts       ← Axios HTTP client
│       │   ├── client.ts      ← API client wrapper
│       │   ├── hooks.ts       ← TanStack Query hooks
│       │   └── socket.ts      ← Socket.IO client
│       ├── components/
│       │   ├── AppShell.tsx   ← Main layout shell
│       │   ├── Sidebar.tsx    ← Navigation sidebar
│       │   ├── ProtectedRoute.tsx ← Auth guard
│       │   ├── dashboard/     ← Dashboard widgets
│       │   ├── document-generator/ ← Document UI components
│       │   ├── settings/      ← Settings panel
│       │   └── ui/            ← shadcn/ui components
│       ├── pages/
│       │   ├── Login.tsx
│       │   ├── Register.tsx
│       │   ├── OtpVerification.tsx
│       │   ├── DashboardPage.tsx
│       │   ├── DocumentGenerator.tsx
│       │   ├── VoiceAgent.tsx
│       │   ├── WhatsAppChat.tsx
│       │   ├── AnalyticsPage.tsx
│       │   ├── DatabasePage.tsx
│       │   ├── SettingsPage.tsx
│       │   ├── ProfilePage.tsx
│       │   ├── AddLogo.tsx
│       │   ├── BusinessSelection.tsx
│       │   ├── BusinessDescription.tsx
│       │   └── ProjectProfile.tsx
│       ├── store/             ← Redux store
│       └── hooks/             ← Custom React hooks
└── voices/                    ← Voice configuration
```

---

## 5. Features & Modules

### 5.1 User Authentication

- **Email/Password Registration** with OTP email verification via Nodemailer
- **Google OAuth** login with Passport.js
- **JWT-based sessions** with configurable expiry
- **Protected routes** on both frontend and backend

### 5.2 Document Generator

The core AI-powered document generation engine:

- **Input**: Natural language description of the document needed
- **AI Processing**: LangChain pipeline with AMD Radion Cloud AI (DeepSeek V4 Pro)
- **Output Formats**: PDF, DOCX, XLSX, CSV, HTML
- **Streaming**: Real-time generation via Socket.IO
- **RAG Support**: Upload reference PDFs for style matching
- **Memory**: Maintains context across document generations
- **Business Context**: Personalizes documents with business name, type, and description

### 5.3 Voice Agent

Twilio-powered voice call handling:

- **Incoming Calls**: Answered by AI with natural conversation
- **Speech Recognition**: Processes caller speech via Twilio's Gather verb
- **AI Response**: AMD Radion Cloud AI generates contextual responses
- **Text-to-Speech**: Local Kokoro TTS for voice synthesis
- **Outbound Calls**: Initiate calls from the dashboard
- **Call Logs**: View history of all calls with message transcripts

### 5.4 WhatsApp Agent

Dual-provider WhatsApp messaging:

- **Twilio WhatsApp**: Traditional Twilio WhatsApp integration
- **Meta Cloud API**: Direct Meta WhatsApp Business API
- **AI Conversations**: Contextual AI responses based on business description
- **Dynamic DB Queries**: AI can query/create data in external databases
- **Conversation History**: Persistent chat history with search
- **Multi-session**: Handles multiple concurrent conversations

### 5.5 Database Agent

Universal database management with guardrails:

- **Supported Types**: PostgreSQL, MongoDB, Google Sheets, Supabase
- **Natural Language Queries**: Ask questions in plain English
- **Guardrails**: Per-operation permissions (Read/Write/Update/Delete)
- **Schema Preview**: Auto-generated schema templates per business type
- **Agent Memory**: Remembers past queries and results
- **Business Types**: Retail, Healthcare, Real Estate, Education, Logistics, Finance, Hospitality, Technology, Manufacturing, Agriculture

### 5.6 Analytics Agent

AI-powered business analytics:

- **Schema-aware**: Understands your database structure
- **Natural Language**: Ask analytical questions in plain English
- **Multi-DB**: Works across all supported database types
- **Voice Analytics**: Specialized agent for voice call data analysis

### 5.7 Project Profile Generator

Professional project documentation:

- **HTML Output**: Beautiful styled document with cover page, cards, tags, timeline
- **PDF Output**: Server-side PDF generation via pdfkit
- **PPT Output**: Professional presentation via pptxgenjs
- **Sections**: Executive Summary, Overview, Features, Tech Stack, Architecture, Team, Timeline, Budget, Risks, Conclusion

### 5.8 Settings & Configuration

- **Business Profile**: Name, type, description
- **Brand & Logo**: Upload and manage brand logos
- **Twilio Configuration**: Account SID, Auth Token, phone numbers
- **Database Credentials**: Connection details for external databases
- **Permission Toggles**: Enable/disable read, write, update, delete operations

---

## 6. API Reference

### 6.1 Authentication

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/register` | Register new user | No |
| POST | `/api/login` | Login | No |
| POST | `/api/verify-email` | Verify OTP | No |
| GET | `/auth/google` | Google OAuth login | No |
| GET | `/auth/google/callback` | Google OAuth callback | No |

### 6.2 User Profile

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/api/user` | Get user profile | JWT |
| PUT | `/api/user` | Update user profile | JWT |

### 6.3 Business & Brand

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/register/business` | Register business | No |
| POST | `/api/register/logo` | Upload logo | No |
| GET | `/api/logo` | Get brand logo | JWT |
| POST | `/api/logo` | Upload brand logo | JWT |
| DELETE | `/api/logo` | Delete brand logo | JWT |

### 6.4 Document Generation

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/generate-document` | Generate document (SSE) | JWT |
| POST | `/api/document/download/:format` | Download document | JWT |
| POST | `/api/document/upload-pdf` | Upload reference PDF | JWT |
| GET | `/api/document/memory` | Get document history | JWT |

### 6.5 Voice Agent

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/voice/incoming` | Incoming call webhook | Twilio |
| POST | `/voice/process-speech` | Process speech input | Twilio |
| GET | `/api/voice/calls` | Get call logs | JWT |
| POST | `/api/voice/test` | Test conversation | JWT |
| POST | `/api/voice/outbound-call` | Make outbound call | JWT |

### 6.6 WhatsApp Agent

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/whatsapp/incoming` | Incoming message (Twilio) | Twilio |
| GET | `/whatsapp/meta-webhook` | Meta webhook verification | Meta |
| POST | `/whatsapp/meta-webhook` | Meta incoming message | Meta |
| GET | `/api/whatsapp/conversations` | List conversations | JWT |
| GET | `/api/whatsapp/conversations/:id` | Get conversation detail | JWT |
| POST | `/api/whatsapp/send` | Send message | JWT |
| POST | `/api/whatsapp/test` | Test conversation | JWT |
| DELETE | `/api/whatsapp/conversations/:id` | Clear conversation | JWT |

### 6.7 Database Agent

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/database/test` | Test DB connection | JWT |
| POST | `/api/database/create-schema` | Create schema | JWT |
| GET | `/api/database/schema-preview/:type` | Preview schema | JWT |
| POST | `/api/database/scan` | Scan database | JWT |
| POST | `/api/database/chat` | Chat with database | JWT |
| POST | `/api/database/agent` | Query with agent | JWT |
| GET | `/api/database/agent-history` | Get agent history | JWT |

### 6.8 Analytics

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/api/analytics/schema/:type` | Get schema preview | JWT |
| POST | `/api/analytics/agent` | Query analytics agent | JWT |
| POST | `/api/analytics/voice-agent` | Voice analytics agent | JWT |

### 6.9 Project Profile

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/project-profile/generate` | Generate HTML profile | JWT |
| POST | `/api/project-profile/ppt` | Generate PPT download | JWT |
| POST | `/api/project-profile/pdf` | Convert HTML to PDF | JWT |
| POST | `/api/project-profile/full` | Generate full profile | JWT |

### 6.10 Settings & History

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/api/settings` | Get settings | JWT |
| PUT | `/api/settings` | Update settings | JWT |
| POST | `/api/settings/twilio/:section` | Save Twilio config | JWT |
| GET | `/api/history/stats` | Get dashboard stats | JWT |
| GET | `/api/history` | Get activity history | JWT |
| DELETE | `/api/history` | Clear history | JWT |

---

## 7. Database Schema

### 7.1 Users (`register`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | User ID |
| firstName | STRING | First name |
| lastName | STRING | Last name |
| email | STRING (Unique) | Email address |
| password | STRING | Hashed password |
| googleId | STRING | Google OAuth ID |
| provider | STRING | Auth provider (local/google) |
| isEmailVerified | BOOLEAN | Email verification status |
| createdAt | DATE | Account creation date |
| updatedAt | DATE | Last update date |

### 7.2 Businesses (`businesses`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | Business ID |
| userId | INTEGER (FK) | Owner user ID |
| businessName | STRING | Business name |
| businessType | STRING | Business category |
| businessDescription | TEXT | Business description |

### 7.3 Logos (`logos`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | Logo ID |
| userId | INTEGER (FK) | Owner user ID |
| businessId | INTEGER (FK) | Associated business |
| logoPath | STRING | File path |
| originalName | STRING | Original filename |

### 7.4 Settings (`settings`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | Settings ID |
| userId | INTEGER (FK, Unique) | Owner user ID |
| businessName | STRING | Business name |
| businessType | STRING | Business category |
| businessDescription | TEXT | Business description |
| dbReadEnabled | BOOLEAN | Read permission |
| dbWriteEnabled | BOOLEAN | Write permission |
| dbUpdateEnabled | BOOLEAN | Update permission |
| dbDeleteEnabled | BOOLEAN | Delete permission |
| twilioAccountSid | STRING | Twilio account SID |
| twilioAuthToken | STRING | Twilio auth token |
| twilioPhoneNumber | STRING | Twilio phone number |
| whatsappProvider | STRING | whatsapp/twilio/meta |
| metaPhoneNumberId | STRING | Meta WhatsApp ID |
| metaAccessToken | STRING | Meta access token |
| metaVerifyToken | STRING | Meta verify token |
| dbType | STRING | Database type |
| dbHost | STRING | Database host |
| dbPort | INTEGER | Database port |
| dbName | STRING | Database name |
| dbUser | STRING | Database username |
| dbPassword | STRING | Database password |
| dbConnectionString | TEXT | Full connection string |

### 7.5 History (`histories`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | History ID |
| userId | INTEGER (FK) | Owner user ID |
| action | STRING | Action type |
| details | TEXT | Action details |
| createdAt | DATE | Timestamp |

### 7.6 Agent Memory (`AgentMemories`)

| Column | Type | Description |
|---|---|---|
| id | INTEGER (PK, Auto) | Memory ID |
| userId | INTEGER (FK) | Owner user ID |
| dbType | STRING | Database type |
| dbName | STRING | Database name |
| sessionId | STRING | Conversation session |
| role | ENUM(user/assistant) | Message role |
| question | TEXT | User question |
| answer | TEXT | AI answer |
| operationType | STRING | DB operation type |
| queryExecuted | TEXT | Executed query |
| rowsAffected | INTEGER | Rows affected |
| success | BOOLEAN | Operation success |

---

## 8. Authentication & Security

### 8.1 JWT Authentication

- Tokens generated with `jsonwebtoken` using a secret key from environment variables
- Default expiry: 1 hour (login), 7 days (Google OAuth)
- Middleware (`authmiddleware.js`) validates tokens on protected routes
- Frontend stores token and sends via `Authorization: Bearer <token>` header

### 8.2 Password Security

- Passwords hashed with `bcryptjs` (salt rounds: 10)
- No plain-text passwords stored

### 8.3 API Security

- **Helmet**: Sets security-related HTTP headers
- **CORS**: Restricted to frontend origin (`http://localhost:5173`)
- **Rate Limiting**: Express rate limiter configured
- **Input Validation**: express-validator on critical endpoints

### 8.4 Database Guardrails

- Each database operation (Read/Write/Update/Delete) has an independent permission toggle
- Guardrail system prompt injected into every AI database query
- Operations blocked at the AI prompt level before execution

---

## 9. Installation & Setup

### 9.1 Prerequisites

- Node.js 20+ 
- PostgreSQL 15+
- Redis (optional, for production)
- Twilio account (for voice/WhatsApp features)
- AMD Radion Cloud AI API key (for LLM features)

### 9.2 Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Server
PORT=4001
SECRET_KEY=your_jwt_secret_key

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=aiassistant
DB_USER=postgres
DB_PASSWORD=your_db_password

# AMD Radion Cloud AI
AMD_RADION_API_KEY=your_amd_radion_api_key
AMD_RADION_API_BASE=https://api.amdradioncloud.ai/inference/v1

# Google OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_SECRET=your_google_secret

# Email (Nodemailer)
EMAIL=your_email@gmail.com
EMAIL_PASSWORD=your_app_password

# Twilio
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=+1234567890
```

### 9.3 Installation Steps

```bash
# 1. Clone the repository
git clone <repo-url>
cd AiAssistant

# 2. Install backend dependencies
cd backend
npm install

# 3. Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# 4. Start the backend server
npm start
# Server runs on http://localhost:4001

# 5. Install frontend dependencies (in a new terminal)
cd frontend
npm install

# 6. Start the frontend dev server
npm run dev
# Frontend runs on http://localhost:5173
```

### 9.4 Database Setup

The application uses Sequelize ORM with auto-sync. On first startup:

```bash
# The database tables are created automatically via db.sync({ alter: true })
# Just ensure PostgreSQL is running and the database exists:

createdb aiassistant
npm start  # Tables created automatically
```

### 9.5 Docker Deployment (Recommended)

The project includes full Docker support for easy deployment. All services (PostgreSQL, Redis, Backend, Frontend) are orchestrated via Docker Compose.

#### Prerequisites

- Docker Engine 24+
- Docker Compose v2+

#### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd AiAssistant

# 2. Create environment file
cp .env.example .env
# Edit .env with your API keys and secrets

# 3. Start all services
docker compose up -d

# 4. Check logs
docker compose logs -f

# 5. Access the application
# Frontend: http://localhost
# Backend API: http://localhost:4001
```

#### Service Architecture

```
┌──────────────┐      ┌──────────────┐
│   Frontend   │──────│   Backend    │
│  (Nginx:80)  │      │ (Express:4001)│
└──────────────┘      └──────┬───────┘
                             │
                    ┌────────┴────────┐
                    │                 │
              ┌─────▼─────┐   ┌──────▼─────┐
              │ PostgreSQL│   │   Redis    │
              │  (:5432)  │   │  (:6379)   │
              └───────────┘   └────────────┘
```

#### Useful Docker Commands

```bash
# Start all services
docker compose up -d

# Rebuild and start (after code changes)
docker compose up -d --build

# View logs
docker compose logs -f
docker compose logs -f backend    # Backend only
docker compose logs -f frontend   # Frontend only

# Stop all services
docker compose down

# Stop and remove volumes (WARNING: deletes database data)
docker compose down -v

# Restart a specific service
docker compose restart backend

# Run commands inside a container
docker compose exec backend sh
docker compose exec postgres psql -U postgres -d omini

# Check container health
docker compose ps
```

#### Environment Variables for Docker

The `docker-compose.yml` reads from a `.env` file in the project root. Key variables:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `your_jwt_secret_key...` | JWT signing secret |
| `DB_NAME` | `omini` | PostgreSQL database name |
| `DB_USER` | `postgres` | PostgreSQL username |
| `DB_PASSWORD` | `Ashish12345687` | PostgreSQL password |
| `AMD_RADION_API_KEY` | — | AMD Radion Cloud AI API key |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_SECRET` | — | Google OAuth client secret |
| `EMAIL` | — | Gmail address for Nodemailer |
| `EMAIL_PASSWORD` | — | Gmail app password |
| `TWILIO_ACCOUNT_SID` | — | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | — | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | — | Twilio phone number |

#### Production Considerations

1. **Change default passwords**: Update `SECRET_KEY` and `DB_PASSWORD` in `.env`
2. **Use Docker secrets**: For production, consider Docker secrets instead of env vars
3. **SSL/TLS**: Add a reverse proxy (Traefik, Caddy, Nginx) with Let's Encrypt
4. **Backup**: Regularly backup the `postgres-data` volume
5. **Monitoring**: Use `docker compose logs` or integrate with a logging service

---

## 10. Development Guide

### 10.1 Adding a New Feature

1. **Backend**: Create a controller in `backend/controller/`
2. **Routes**: Add routes in `backend/server.js`
3. **Model**: Define Sequelize model in `backend/model/` (if needed)
4. **Frontend**: Create page in `frontend/src/pages/`
5. **Router**: Add route in `frontend/src/App.tsx`
6. **API Client**: Add API calls in `frontend/src/api/`

### 10.2 Code Conventions

- **Backend**: CommonJS (`require`/`module.exports`), Express 5
- **Frontend**: TypeScript, React 19, functional components with hooks
- **Styling**: Tailwind CSS v4 utility classes
- **State**: Redux Toolkit for global state, TanStack Query for server state
- **API**: Axios instance with interceptors for auth token injection

### 10.3 AI Integration Pattern

All AI features follow this pattern:

```javascript
// 1. Call AMD Radion Cloud AI API
const response = await fetch('https://api.amdradioncloud.ai/inference/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.amd_radion_api_key}`
  },
  body: JSON.stringify({
    model: 'accounts/amd/models/deepseek-v4-flash',
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userMessage }
    ],
    max_tokens: 2000,
    temperature: 0.7
  })
});
```

Or using LangChain for more complex pipelines:

```javascript
const chain = RunnableSequence.from([
  PromptTemplate.fromTemplate(template),
  new ChatOpenAI({ ... }),
  new StringOutputParser(),
]);
const result = await chain.invoke({ ... });
```

---

## 11. Deployment

### 11.1 Docker Deployment (Recommended)

The project includes full Docker support. See [Section 9.5](#95-docker-deployment-recommended) for complete instructions.

```bash
# Quick start
docker compose up -d
```

### 11.2 Production Build (Without Docker)

```bash
# Build frontend
cd frontend
npm run build
# Output in frontend/dist/

# Serve from backend
# Update backend/server.js to serve static files from frontend/dist
```

### 11.3 Environment-Specific Configuration

| Environment | Frontend URL | Backend URL | Notes |
|---|---|---|---|
| Development | localhost:5173 | localhost:4001 | Vite dev server |
| Docker | localhost | localhost:4001 | Nginx serves frontend |
| Production | yourdomain.com | yourdomain.com/api | Built files served by Nginx |

---

## 12. Contributing

### 12.1 Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### 12.2 Code Review Guidelines

- All PRs require at least one review
- Ensure TypeScript types are properly defined
- Add error handling for all API calls
- Test both success and failure scenarios
- Update documentation for new features

---

## License

This project is licensed under the ISC License.

---

*Generated by AiAssistant Project Profile Generator — August 2026*

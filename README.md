# 🐢 EcoChroniclez — AI-Powered Environmental Education Platform

EcoChroniclez is a gamified environmental-education web app for students,
with a 17-level quiz, a locally-powered "Eco Tutor" chatbot, an in-browser
adaptive learning model, an Eco Waste Identification module, a live
Firestore leaderboard, and a full Teacher/Admin analytics dashboard.

**This project runs entirely on the free Firebase Spark plan.** No billing
account, no credit card, and no paid API key is required at any point.

---

## ✅ 100% Free-Tier Compliant

| Requirement | Status |
|---|---|
| Firebase Storage | ❌ Not used |
| Cloud Functions | ❌ Not used |
| Gemini / OpenAI / Vertex AI / Cloud Vision | ❌ Not used |
| Firebase Authentication | ❌ Not used (lightweight localStorage login instead) |
| Firestore | ✅ Used (free on Spark) |
| Firebase Hosting | ✅ Used (free on Spark) |
| TensorFlow.js | ✅ Used, 100% in-browser, no server/API calls |

Everything that looks "AI-powered" in this app — the Eco Tutor chat, the
waste identification cards, the adaptive difficulty pacing, and the
teacher's "AI Insights" panel — is powered by **curated local knowledge
bases, keyword matching, rule-based logic, and an in-browser TensorFlow.js
model**. Nothing calls an external AI API, so nothing can rack up a bill.

---

## ✨ Features

- **Student registration & login** — name, class, language, stored in `localStorage` (no Firebase Auth needed)
- **17-level environmental quiz** — Beginner (1–5), Intermediate (6–11), Advanced (12–17), with lives, XP, and a progress bar
- **XP, badges & streaks** — Eco Beginner → Green Warrior → Earth Protector → Eco Champion
- **Eco Tutor chatbot** — answers environmental questions from a curated local knowledge base with keyword matching
- **Eco Waste Identification** — tap a sample waste card (plastic bottle, banana peel, battery, etc.) to see its category, recyclability, and disposal tips — no photo upload, no Firebase Storage
- **Adaptive learning pace** — a small TensorFlow.js network trains **in the browser** on your class's real Firestore quiz history to suggest "accelerate / steady / review" pacing
- **Live Firestore leaderboard** — ranked by Eco Points, updates in real time as students complete levels
- **Teacher/Admin dashboard** — total students, average score, top performer, level completion, language usage, at-risk student list, rule-based class insights, and a downloadable CSV report
- **Bilingual UI** — English and Tamil (see `LANGUAGES.md` note below for extending this)
- **Responsive, animated eco-themed UI** — works on mobile, tablet, and desktop

---

## 📁 Project Structure

```
EcoChroniclez/
├── index.html            ← Student app (self-contained: markup + styles + core logic)
├── teacher.html           ← Teacher/Admin dashboard shell
├── teacher.css            ← Teacher dashboard styling
├── teacher.js             ← Teacher dashboard logic (Firestore reads, filters, CSV export)
├── firebase.js            ← THE single Firestore data layer (init + all reads/writes)
├── firebase.json          ← Firebase Hosting + Firestore config (Spark-plan safe)
├── firestore.rules        ← Firestore security rules (public read/create, no update/delete)
├── js/
│   ├── adaptiveML.js       ← In-browser TensorFlow.js adaptive-pacing model
│   ├── ecoFeatures.js      ← Local recommendation card + adaptive pace badge wiring
│   ├── teacherAI.js        ← Teacher dashboard charts + rule-based "AI Insights"
│   └── wasteId.js          ← Eco Waste Identification cards + local knowledge base
├── README.md               ← This file
├── INSTALLATION.md         ← Local setup guide
├── FIREBASE_SETUP.md       ← Firebase project + Firestore setup guide
└── DEPLOYMENT.md           ← Firebase Hosting deployment guide
```

> **Why isn't there a separate `style.css` / `script.js` / `lang/` / `data/`
> folder?** The live student app (`index.html`) is intentionally
> self-contained — its CSS and core JS are inline in one file so it has
> zero build step and can be opened straight from Firebase Hosting. The
> teacher dashboard *does* use the split `teacher.css` / `teacher.js`
> pattern. If you'd like the student app's CSS/JS split out into external
> files or the quiz/tutor content moved into `data/` and `lang/` JSON
> files, that's a clean follow-up refactor — just ask.

---

## 🗄️ Firestore Collections

Only two collections are used, both free on Spark:

- **`scores`** — one document per completed quiz attempt (`name`, `studentClass`, `level`, `score`, `total`, `language`, `timestamp`)
- **`waste_logs`** — one document per Eco Waste Identification card tapped (`studentName`, `studentClass`, `itemName`, `wasteType`, `biodegradable`, `timestamp`)

There is no `students` collection because there's no Firebase Auth —
student identity/progress lives in `localStorage` on their own device,
and the `scores`/`waste_logs` collections are what feed the shared
leaderboard and teacher dashboard.

---

## 🚀 Quick Start

1. Read **[INSTALLATION.md](./INSTALLATION.md)** to run the app locally.
2. Read **[FIREBASE_SETUP.md](./FIREBASE_SETUP.md)** to connect your own free Firebase project.
3. Read **[DEPLOYMENT.md](./DEPLOYMENT.md)** to deploy to Firebase Hosting — for free.

**Teacher dashboard password:** `teacher123` (change it in `teacher.js` — see FIREBASE_SETUP.md's security note).

---

## 🔒 Security Note

The Firebase web config in `firebase.js` (API key, project ID, etc.) is
**safe to expose publicly** — Firebase web app configs are not secrets;
access is controlled by your **Firestore security rules**
(`firestore.rules`), not by hiding the config. Before going live with your
own class:

1. Swap in **your own** Firebase project's config (don't reuse the sample one shipped in this repo).
2. Review `firestore.rules` and tighten it if you need more than "anyone can create, nobody can update/delete."
3. Change the teacher password in `teacher.js`.

See `FIREBASE_SETUP.md` for the full walkthrough.

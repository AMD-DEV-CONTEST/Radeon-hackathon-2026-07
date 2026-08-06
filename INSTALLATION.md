# 🛠️ Installation Guide

EcoChroniclez has **no build step and no dependencies to install** — it's
plain HTML, CSS, and vanilla JavaScript (ES modules), plus two CDN-loaded
libraries (Chart.js for the teacher dashboard, TensorFlow.js for adaptive
pacing). You do not need Node.js, npm, or any package manager to run it.

## 1. Get the project files

Unzip the project, or clone it, so you have a folder that looks like:

```
EcoChroniclez/
├── index.html
├── teacher.html
├── firebase.js
├── js/
└── ...
```

## 2. Connect Firebase (one-time)

Before running the app, follow **[FIREBASE_SETUP.md](./FIREBASE_SETUP.md)**
to create your own free Firebase project and paste its config into
`firebase.js`. The app will still *load* without this step, but quiz
scores, the leaderboard, and the teacher dashboard need Firestore to work.

## 3. Run it locally

Because `index.html` and `teacher.html` use ES module `<script type="module">`
imports (for `firebase.js`), you **cannot** just double-click the HTML
file and open it with `file://` — browsers block ES module imports over
`file://` for security reasons. Serve the folder over `http://localhost`
instead, using any of these:

### Option A — Python (already installed on most systems)
```bash
cd EcoChroniclez
python3 -m http.server 8080
```
Then open **http://localhost:8080**

### Option B — Node's `http-server` (if you have Node.js)
```bash
npx http-server -p 8080
```

### Option C — VS Code "Live Server" extension
Right-click `index.html` → **Open with Live Server**.

### Option D — Firebase Hosting emulator (closest to production)
```bash
npm install -g firebase-tools
firebase login
firebase emulators:start --only hosting
```

## 4. Try it out

- Open the served URL → you'll land on the student registration/login screen.
- Register with a name, class, and language → you're taken to the dashboard.
- Complete a quiz level → your score is written to Firestore and shows up on the **Leaderboard** and in the **Teacher Dashboard**.
- Open `teacher.html` in another tab → log in with `teacher123` (see FIREBASE_SETUP.md to change this) to see the class-wide analytics.

## 5. Next steps

- **[FIREBASE_SETUP.md](./FIREBASE_SETUP.md)** — connect your own Firebase project
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — publish it live on Firebase Hosting, for free

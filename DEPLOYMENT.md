# 🚀 Deployment Guide (Firebase Hosting — Free, Spark Plan)

This deploys the whole project to a public `https://YOUR-PROJECT.web.app`
URL using only Firebase Hosting's free Spark tier.

## Prerequisites

- You've completed **[FIREBASE_SETUP.md](./FIREBASE_SETUP.md)** (project created, config pasted into `firebase.js`, Firestore enabled).
- Node.js installed (only needed for the `firebase-tools` CLI — the app itself has no dependencies).

## 1. Install the Firebase CLI

```bash
npm install -g firebase-tools
```

## 2. Log in

```bash
firebase login
```

This opens a browser window to authenticate with your Google account.

## 3. Connect this folder to your Firebase project

From the project root (where `firebase.json` lives):

```bash
firebase use --add
```

Select the project you created in `FIREBASE_SETUP.md`, and give it an
alias (e.g. `default`).

> This project already ships a ready-to-use `firebase.json` and
> `firestore.rules`, so you can skip `firebase init` entirely — running
> `firebase use --add` is enough to link the folder to your project.

## 4. Deploy

```bash
firebase deploy
```

This uploads:
- Every file in the project (per `firebase.json`'s `hosting.public: "."`) to Firebase Hosting
- Your `firestore.rules` to Firestore

Documentation files (`*.md`) are excluded from the Hosting upload via the
`ignore` list in `firebase.json`, so they don't clutter your live site.

## 5. Visit your live app

The CLI prints two URLs when it finishes, e.g.:

```
Hosting URL: https://my-ecochroniclez.web.app
```

- Student app: `https://my-ecochroniclez.web.app/index.html`
- Teacher dashboard: `https://my-ecochroniclez.web.app/teacher.html`

Both are on the free Spark plan — Firebase Hosting's free tier includes a
generous monthly bandwidth and storage allowance, more than enough for a
classroom or school project.

## 6. Redeploying after changes

Any time you edit the HTML/CSS/JS, just run:

```bash
firebase deploy
```

again. There's no build step to run first.

## Troubleshooting

- **"Permission denied" on Firestore reads/writes in production** → double-check you published `firestore.rules` (Step 4 of `FIREBASE_SETUP.md`, or redeploy with `firebase deploy --only firestore:rules`).
- **Blank page after deploy** → open the browser console; if you see a Firebase "invalid API key" error, re-check the config you pasted into `firebase.js`.
- **Nothing shows on the leaderboard/teacher dashboard** → that's expected until at least one student completes a quiz level (Firestore starts empty).

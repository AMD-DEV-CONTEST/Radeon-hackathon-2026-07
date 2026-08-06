# 🔥 Firebase Setup Guide (Spark Plan — Free, No Credit Card)

This project needs exactly **two** Firebase products, both free forever
on the **Spark plan**:

- **Firestore** (database) — stores quiz scores and waste-log activity
- **Firebase Hosting** (static hosting) — serves the HTML/CSS/JS files

You will **not** enable, and do **not** need: Authentication, Storage,
Cloud Functions, or any Blaze (pay-as-you-go) upgrade.

---

## 1. Create a Firebase project

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** → give it a name (e.g. `my-ecochroniclez`) → follow the prompts.
3. When asked about Google Analytics, you can safely **disable** it — not needed for this project.
4. Confirm your project's plan is **Spark** (this is the default for new projects — you are not asked for a credit card).

## 2. Create a Web App inside the project

1. In the Firebase Console, open your project → click the **`</>`** (Web) icon to "Add app."
2. Give it a nickname (e.g. `EcoChroniclez Web`) — you do **not** need to check "Also set up Firebase Hosting" here (we'll do that via CLI in `DEPLOYMENT.md`).
3. Firebase will show you a `firebaseConfig` object like:

```js
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "my-ecochroniclez.firebaseapp.com",
  projectId: "my-ecochroniclez",
  messagingSenderId: "...",
  appId: "1:...:web:..."
};
```

4. Copy this object.

## 3. Paste your config into the project

Open **`firebase.js`** in the project root and replace the sample
`firebaseConfig` object with your own:

```js
const firebaseConfig = {
  apiKey: "YOUR_KEY_HERE",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT",
  messagingSenderId: "YOUR_SENDER_ID",
  appId: "YOUR_APP_ID",
};
```

That's it — `firebase.js` is the **only** file that initializes Firebase.
Every other file (`teacher.js`, `js/wasteId.js`, `js/adaptiveML.js`, and
the inline module script in `index.html`) imports its Firestore access
from this one file, so you only ever need to update your config in one
place.

> **Is it safe to have this config visible in a public repo/zip?**
> Yes. A Firebase web config is an identifier, not a secret — it's
> equivalent to a database URL, not a password. Actual access control is
> enforced by your **Firestore security rules** (next step), not by
> hiding this object.

## 4. Enable Firestore

1. In the Firebase Console, open **Build → Firestore Database**.
2. Click **Create database**.
3. Choose **Start in production mode** (we ship our own rules below) and pick a location close to your students.
4. Once created, go to the **Rules** tab and paste in the contents of this project's `firestore.rules`:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /scores/{scoreId} {
      allow read: if true;
      allow create: if true;
      allow update, delete: if false;
    }
    match /waste_logs/{logId} {
      allow read: if true;
      allow create: if true;
      allow update, delete: if false;
    }
  }
}
```

5. Click **Publish**.

This allows anyone using the app to *submit* a quiz score or waste-log
entry, and anyone (including the teacher dashboard) to *read* all of
them, but nobody can edit or delete existing records from the client.

> If you deploy with the Firebase CLI (see `DEPLOYMENT.md`), running
> `firebase deploy` will also push `firestore.rules` automatically — you
> don't have to paste it into the console by hand if you deploy that way.

## 5. Change the teacher password

Open `teacher.js` and change:

```js
const TEACHER_PASSWORD = 'teacher123';
```

to something only your teaching staff knows. This is a simple client-side
gate (appropriate for a classroom project on Spark, since there's no
Firebase Auth) — it hides the dashboard from casual students, but is not
a substitute for real authentication if you need strict access control.

## 6. You're done

No billing account, no Storage bucket, no Cloud Functions deploy, no API
key for any AI service. Continue to **[DEPLOYMENT.md](./DEPLOYMENT.md)**
to publish the app.

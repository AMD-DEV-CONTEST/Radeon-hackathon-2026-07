import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import {
  getFirestore,
  collection,
  addDoc,
  getDocs,
  query,
  orderBy
}  from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";

/* ============================================================
   Firebase Configuration
   Replace this with YOUR Firebase project's configuration
============================================================ */

const firebaseConfig = {
  apiKey: "AIzaSyBg8l4nUgzJnSpkha85Gw6dhPN-ULPo0us",
  authDomain: "ecochronicles-48c85.firebaseapp.com",
  projectId: "ecochronicles-48c85",
  storageBucket: "ecochronicles-48c85.firebasestorage.app",
  messagingSenderId: "98034293324",
  appId: "1:98034293324:web:d2cf654dd03fe343af32e9"
};

/* ============================================================
   Initialize Firebase
============================================================ */

const app =
  getApps().length > 0
    ? getApps()[0]
    : initializeApp(firebaseConfig);

const db = getFirestore(app);

/* ============================================================
   Save Quiz Score
============================================================ */

export async function saveScore(
  studentName,
  level,
  score,
  total,
  language,
  studentClass = ""
) {
  try {
    await addDoc(collection(db, "scores"), {
      name: studentName,
      studentClass,
      level,
      score,
      total,
      language,
      timestamp: new Date().toISOString()
    });

    return true;
  } catch (error) {
    console.error("Error saving score:", error);
    return false;
  }
}

/* ============================================================
   Get All Quiz Scores
============================================================ */

export async function getAllScores() {
  try {
    const q = query(
      collection(db, "scores"),
      orderBy("timestamp", "desc")
    );

    const snapshot = await getDocs(q);

    const scores = [];

    snapshot.forEach((doc) => {
      scores.push({
        id: doc.id,
        ...doc.data()
      });
    });

    return scores;
  } catch (error) {
    console.error("Error getting scores:", error);
    return [];
  }
}

/* ============================================================
   Log Waste Identification
============================================================ */

export async function logWasteIdentification({
  studentName,
  studentClass,
  itemName,
  wasteType,
  biodegradable
}) {
  try {
    await addDoc(collection(db, "waste_logs"), {
      studentName: studentName || "",
      studentClass: studentClass || "",
      itemName,
      wasteType,
      biodegradable: !!biodegradable,
      timestamp: new Date().toISOString()
    });

    return true;
  } catch (error) {
    console.error("Error logging waste identification:", error);
    return false;
  }
}

/* ============================================================
   Get Waste Logs
============================================================ */

export async function getAllWasteLogs() {
  try {
    const q = query(
      collection(db, "waste_logs"),
      orderBy("timestamp", "desc")
    );

    const snapshot = await getDocs(q);

    const logs = [];

    snapshot.forEach((doc) => {
      logs.push({
        id: doc.id,
        ...doc.data()
      });
    });

    return logs;
  } catch (error) {
    console.error("Error getting waste logs:", error);
    return [];
  }
}
import { initializeApp } from "firebase/app";
import { 
  getAuth, 
  signInWithPopup, 
  GoogleAuthProvider, 
  signOut,
  User as FirebaseUser
} from "firebase/auth";
import { 
  getFirestore, 
  doc, 
  getDoc, 
  setDoc, 
  collection, 
  query, 
  where, 
  getDocs, 
  orderBy, 
  deleteDoc,
  getDocFromServer,
  Timestamp
} from "firebase/firestore";
import { UserProfile, ChatSession, SymptomCheckResult, ChatMessage } from "../types";

// Construct Firebase Config dynamically from Environment Variables
const env = (import.meta as any).env || {};

const activeConfig = {
  apiKey: env.VITE_FIREBASE_API_KEY || "",
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN || "",
  projectId: env.VITE_FIREBASE_PROJECT_ID || "",
  storageBucket: env.VITE_FIREBASE_STORAGE_BUCKET || "",
  messagingSenderId: env.VITE_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: env.VITE_FIREBASE_APP_ID || "",
  measurementId: env.VITE_FIREBASE_MEASUREMENT_ID || ""
};

const activeDatabaseId = env.VITE_FIREBASE_FIRESTORE_DATABASE_ID || "(default)";

// Initialize Firebase
const app = initializeApp(activeConfig);
export const db = activeDatabaseId && activeDatabaseId !== "(default)"
  ? getFirestore(app, activeDatabaseId)
  : getFirestore(app); /* CRITICAL: The app will break without this line */
export const auth = getAuth(app);

// Google Auth Provider
export const googleProvider = new GoogleAuthProvider();

// Standard Error Handling for Firestore as required by Skill
export enum OperationType {
  CREATE = "create",
  UPDATE = "update",
  DELETE = "delete",
  LIST = "list",
  GET = "get",
  WRITE = "write",
}

export interface FirestoreErrorInfo {
  error: string;
  operationType: OperationType;
  path: string | null;
  authInfo: {
    userId?: string | null;
    email?: string | null;
    emailVerified?: boolean | null;
    isAnonymous?: boolean | null;
    tenantId?: string | null;
    providerInfo?: {
      providerId?: string | null;
      email?: string | null;
    }[];
  };
}

export function handleFirestoreError(error: unknown, operationType: OperationType, path: string | null): never {
  const errInfo: FirestoreErrorInfo = {
    error: error instanceof Error ? error.message : String(error),
    authInfo: {
      userId: auth.currentUser?.uid,
      email: auth.currentUser?.email,
      emailVerified: auth.currentUser?.emailVerified,
      isAnonymous: auth.currentUser?.isAnonymous,
      tenantId: auth.currentUser?.tenantId,
      providerInfo: auth.currentUser?.providerData?.map(provider => ({
        providerId: provider.providerId,
        email: provider.email,
      })) || []
    },
    operationType,
    path
  };
  console.error("Firestore Error: ", JSON.stringify(errInfo));
  throw new Error(JSON.stringify(errInfo));
}

// Check Firestore connection on startup (as required by skill)
export async function testConnection() {
  try {
    await getDocFromServer(doc(db, "test", "connection"));
    console.log("[Firebase] Firestore connection test passed.");
  } catch (error) {
    if (error instanceof Error && error.message.includes("the client is offline")) {
      console.error("[Firebase] Firestore connection test failed. Please check your configuration.");
    }
  }
}

// --------------------------------------------------------------------
// USER PROFILE FUNCTIONS
// --------------------------------------------------------------------

export async function getUserProfile(uid: string): Promise<UserProfile | null> {
  const path = `users/${uid}`;
  try {
    const docRef = doc(db, "users", uid);
    const docSnap = await getDoc(docRef);
    if (docSnap.exists()) {
      return { uid, ...docSnap.data() } as UserProfile;
    }
    return null;
  } catch (error) {
    handleFirestoreError(error, OperationType.GET, path);
  }
}

export async function saveUserProfile(uid: string, profile: Partial<UserProfile>): Promise<void> {
  const path = `users/${uid}`;
  try {
    const docRef = doc(db, "users", uid);
    // Sanitize profile details to remove 'undefined' properties which crash Firestore writes
    const sanitizedProfile: Record<string, any> = {};
    Object.keys(profile).forEach((key) => {
      const val = (profile as any)[key];
      if (val !== undefined) {
        sanitizedProfile[key] = val;
      }
    });

    await setDoc(docRef, {
      ...sanitizedProfile,
      updatedAt: Timestamp.now()
    }, { merge: true });
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}

// Helper to safely get timestamp in milliseconds for client-side sorting
const getTimestampMillis = (val: any): number => {
  if (!val) return 0;
  if (typeof val.toMillis === "function") return val.toMillis();
  if (typeof val.getTime === "function") return val.getTime();
  if (val.seconds !== undefined) return val.seconds * 1000 + (val.nanoseconds ? Math.floor(val.nanoseconds / 1000000) : 0);
  if (typeof val === "number") return val;
  const parsed = new Date(val).getTime();
  return isNaN(parsed) ? 0 : parsed;
};

// --------------------------------------------------------------------
// CONSULTATION CHAT HISTORY FUNCTIONS
// --------------------------------------------------------------------

export async function getChatSessions(userId: string): Promise<ChatSession[]> {
  const path = "chats";
  try {
    const chatsRef = collection(db, "chats");
    const q = query(
      chatsRef, 
      where("userId", "==", userId)
    );
    const querySnapshot = await getDocs(q);
    const sessions: ChatSession[] = [];
    querySnapshot.forEach((doc) => {
      const data = doc.data();
      sessions.push({
        id: doc.id,
        userId: data.userId,
        title: data.title,
        createdAt: data.createdAt,
        messages: data.messages || []
      });
    });
    // Sort descending by createdAt
    sessions.sort((a, b) => getTimestampMillis(b.createdAt) - getTimestampMillis(a.createdAt));
    return sessions;
  } catch (error) {
    handleFirestoreError(error, OperationType.LIST, path);
  }
}

export async function saveChatSession(
  userId: string, 
  sessionId: string, 
  title: string, 
  messages: ChatMessage[],
  isNew: boolean = false
): Promise<void> {
  const path = `chats/${sessionId}`;
  try {
    const docRef = doc(db, "chats", sessionId);
    const dataToSave: any = {
      userId,
      title,
      messages
    };
    if (isNew) {
      dataToSave.createdAt = Timestamp.now();
    }
    await setDoc(docRef, dataToSave, { merge: true });
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  const path = `chats/${sessionId}`;
  try {
    const docRef = doc(db, "chats", sessionId);
    await deleteDoc(docRef);
  } catch (error) {
    handleFirestoreError(error, OperationType.DELETE, path);
  }
}

// --------------------------------------------------------------------
// SYMPTOM CHECK HISTORY FUNCTIONS
// --------------------------------------------------------------------

export async function getSymptomChecks(userId: string): Promise<SymptomCheckResult[]> {
  const path = "symptomChecks";
  try {
    const checksRef = collection(db, "symptomChecks");
    const q = query(
      checksRef, 
      where("userId", "==", userId)
    );
    const querySnapshot = await getDocs(q);
    const checks: SymptomCheckResult[] = [];
    querySnapshot.forEach((doc) => {
      const data = doc.data();
      checks.push({
        id: doc.id,
        userId: data.userId,
        createdAt: data.createdAt,
        symptoms: data.symptoms || [],
        conditions: data.conditions || [],
        riskLevel: data.riskLevel || "Low"
      });
    });
    // Sort descending by createdAt
    checks.sort((a, b) => getTimestampMillis(b.createdAt) - getTimestampMillis(a.createdAt));
    return checks;
  } catch (error) {
    handleFirestoreError(error, OperationType.LIST, path);
  }
}

export async function saveSymptomCheck(userId: string, symptoms: string[], conditions: string[], riskLevel: "Low" | "Moderate" | "High"): Promise<void> {
  const id = `check_${Date.now()}`;
  const path = `symptomChecks/${id}`;
  try {
    const docRef = doc(db, "symptomChecks", id);
    await setDoc(docRef, {
      userId,
      symptoms,
      conditions,
      riskLevel,
      createdAt: Timestamp.now()
    });
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}

// Run connection check immediately
testConnection();

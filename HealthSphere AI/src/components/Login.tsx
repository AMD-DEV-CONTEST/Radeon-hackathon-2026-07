import React, { useState } from "react";
import { 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword, 
  signInWithPopup, 
  GoogleAuthProvider 
} from "firebase/auth";
import { auth, googleProvider, saveUserProfile } from "../lib/firebase";
import { 
  ShieldCheck, Mail, Lock, Sparkles, LogIn, ArrowRight, 
  Sun, Moon, HelpCircle, ExternalLink 
} from "lucide-react";
import { motion } from "motion/react";

interface LoginProps {
  onLoginSuccess: (user: any, isGuest: boolean) => void;
  darkMode: boolean;
  toggleDarkMode: () => void;
}

export default function Login({ onLoginSuccess, darkMode, toggleDarkMode }: LoginProps) {
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [errorType, setErrorType] = useState<"unauthorized-domain" | "operation-not-allowed" | "popup-blocked" | "other" | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Please fill in all fields.");
      setErrorType("other");
      return;
    }
    setLoading(true);
    setError(null);
    setErrorType(null);

    try {
      if (isSignUp) {
        const userCredential = await createUserWithEmailAndPassword(auth, email, password);
        const user = userCredential.user;
        // Save initial user profile in Firestore
        await saveUserProfile(user.uid, {
          email: user.email,
          displayName: email.split("@")[0],
          createdAt: new Date(),
        });
        onLoginSuccess(user, false);
      } else {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        onLoginSuccess(userCredential.user, false);
      }
    } catch (err: any) {
      console.error(err);
      let errMsg = "An error occurred during authentication.";
      setErrorType("other");
      
      if (err.code === "auth/operation-not-allowed") {
        setErrorType("operation-not-allowed");
        errMsg = "Email/Password sign-in is currently disabled in your Firebase console.";
      } else if (err.code === "auth/user-not-found" || err.code === "auth/wrong-password" || err.code === "auth/invalid-credential") {
        errMsg = "Invalid email or password combination.";
      } else if (err.code === "auth/email-already-in-use") {
        errMsg = "This email is already registered.";
      } else if (err.code === "auth/weak-password") {
        errMsg = "Password must be at least 6 characters.";
      } else if (err.code === "auth/invalid-email") {
        errMsg = "Please enter a valid email address.";
      } else {
        errMsg = err.message || errMsg;
      }
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setError(null);
    setErrorType(null);
    setLoading(true);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const user = result.user;
      await saveUserProfile(user.uid, {
        email: user.email,
        displayName: user.displayName || user.email?.split("@")[0] || "Anonymous User",
        createdAt: new Date(),
      });
      onLoginSuccess(user, false);
    } catch (err: any) {
      console.error("Google login failed", err);
      if (err.code === "auth/unauthorized-domain") {
        setErrorType("unauthorized-domain");
        setError("This domain is not authorized for Google Sign-In in your Firebase Project.");
      } else if (err.code === "auth/popup-blocked") {
        setErrorType("popup-blocked");
        setError("The Google Sign-In popup was blocked by your browser.");
      } else if (err.code !== "auth/popup-closed-by-user") {
        setErrorType("other");
        setError(err.message || "Google sign-in failed. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGuestLogin = () => {
    onLoginSuccess(null, true);
  };

  return (
    <div id="login-container" className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col md:flex-row relative transition-colors duration-300">
      
      {/* Floating Theme Toggle */}
      <div className="absolute top-4 right-4 z-50">
        <button
          id="login-theme-toggle-btn"
          onClick={toggleDarkMode}
          className="p-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 rounded-xl shadow-sm transition-all cursor-pointer flex items-center justify-center"
          title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
        >
          {darkMode ? <Sun className="w-4.5 h-4.5 text-amber-400" /> : <Moon className="w-4.5 h-4.5 text-slate-600" />}
        </button>
      </div>

      {/* Left side: Hero Branding / Clinical Presentation */}
      <div id="login-marketing-sidebar" className="w-full md:w-[45%] bg-gradient-to-br from-blue-900 to-slate-900 text-white p-8 md:p-12 flex flex-col justify-between relative overflow-hidden">
        {/* Subtle background graphics */}
        <div className="absolute right-0 top-0 bottom-0 w-2/3 opacity-5 pointer-events-none">
          <svg className="w-full h-full text-white" viewBox="0 0 100 100" preserveAspectRatio="none">
            <path d="M0,50 Q25,20 50,50 T100,50" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M0,70 Q25,40 50,70 T100,70" fill="none" stroke="currentColor" strokeWidth="1" />
          </svg>
        </div>

        {/* Top brand heading */}
        <div className="flex items-center gap-3 relative z-10">
          <div className="w-9 h-9 rounded-lg bg-blue-500/20 backdrop-blur-sm border border-blue-400/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <rect x="5" y="5" width="14" height="14" rx="4" />
              <path d="M12 8v8M8 12h8" />
            </svg>
          </div>
          <span className="font-sans font-bold text-lg tracking-tight">
            HealthSphere <span className="text-blue-400 font-semibold">AI</span>
          </span>
        </div>

        {/* Central statement */}
        <div className="my-12 md:my-0 space-y-6 relative z-10">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-xs font-semibold text-blue-300">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Intelligent Public Health Assistant</span>
          </div>
          <h1 className="text-3xl md:text-4xl font-sans font-bold tracking-tight leading-[1.15] text-slate-100">
            Professional AI health consultations, accessible instantly.
          </h1>
          <p className="text-sm text-slate-300 font-normal leading-relaxed">
            Consult our expert-trained AI model, cross-check symptoms with our diagnostic library, and store consultation archives safely in our secure Firebase database.
          </p>

          <div className="pt-4 space-y-3">
            {[
              "Encrypted, relational Firestore chat history",
              "Advanced symptom checker with clinical warning triage",
              "Official public health disease library and prevention guides",
              "Verified emergency hospital directories and contacts"
            ].map((feature, i) => (
              <div key={i} className="flex items-start gap-2 text-xs font-medium text-slate-300">
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <span>{feature}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom medical notice */}
        <div className="text-[11px] text-slate-400 leading-relaxed border-t border-slate-800 pt-4 relative z-10">
          Disclaimer: This service provides artificial intelligence-powered educational material. It does not replace professional diagnosis, treatment, or certified medical advice.
        </div>
      </div>

      {/* Right side: Clean, Modern Auth Form */}
      <div id="login-form-area" className="flex-1 flex items-center justify-center p-6 md:p-12 bg-slate-50 dark:bg-slate-950 transition-colors">
        <div className="w-full max-w-md bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800/80 rounded-2xl shadow-xl shadow-slate-200/50 dark:shadow-none p-8 transition-all">
          
          <div className="text-center md:text-left mb-6">
            <h2 id="login-title-h2" className="text-2xl font-sans font-bold tracking-tight text-slate-900 dark:text-white">
              {isSignUp ? "Create your health profile" : "Welcome back"}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              {isSignUp ? "Register an account to store and sync your consultations." : "Access your historical medical reports and chat archives."}
            </p>
          </div>

          {/* Actionable Help Banner - Unauthorized Domain */}
          {error && errorType === "unauthorized-domain" && (
            <div id="login-domain-error" className="mb-6 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 rounded-xl text-xs text-amber-800 dark:text-amber-300">
              <div className="font-bold flex items-center gap-1.5 text-sm mb-1.5 text-amber-900 dark:text-amber-200">
                <HelpCircle className="w-4 h-4 text-amber-500 shrink-0" />
                <span>Authorized Domain Required</span>
              </div>
              <p className="leading-relaxed mb-2.5">
                The domain <code className="bg-amber-100 dark:bg-amber-950/60 px-1 py-0.5 rounded font-mono font-bold text-[11px]">{window.location.host}</code> needs to be added to your Firebase project's Authorized Domains list.
              </p>
              <div className="space-y-1.5 pl-3 list-decimal font-medium mb-3">
                <div>1. Go to the <a href="https://console.firebase.google.com/" target="_blank" rel="noopener noreferrer" className="underline font-bold inline-flex items-center gap-0.5 hover:text-amber-600 dark:hover:text-amber-400">Firebase Console <ExternalLink className="w-3 h-3" /></a></div>
                <div>2. Select your project and navigate to <strong>Authentication &gt; Settings &gt; Authorized domains</strong></div>
                <div>3. Click <strong>Add domain</strong> and paste <code className="bg-amber-100 dark:bg-amber-950/60 px-1 py-0.5 rounded font-mono font-bold text-[11px]">{window.location.hostname}</code></div>
              </div>
              <div className="text-[11px] bg-amber-100/50 dark:bg-amber-950/40 p-2.5 rounded border border-amber-200/40">
                💡 <strong>Tip:</strong> If popups are restricted inside this iframe, click the <strong>"Open in New Tab"</strong> button in the top right of AI Studio to open the app directly.
              </div>
            </div>
          )}

          {/* Actionable Help Banner - Operation Not Allowed */}
          {error && errorType === "operation-not-allowed" && (
            <div id="login-provider-error" className="mb-6 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 rounded-xl text-xs text-amber-800 dark:text-amber-300">
              <div className="font-bold flex items-center gap-1.5 text-sm mb-1.5 text-amber-900 dark:text-amber-200">
                <HelpCircle className="w-4 h-4 text-amber-500 shrink-0" />
                <span>Email/Password Provider Disabled</span>
              </div>
              <p className="leading-relaxed mb-2.5">
                The standard Email/Password sign-in method is currently disabled in your Firebase Console.
              </p>
              <div className="space-y-1.5 pl-3 list-decimal font-medium">
                <div>1. Go to the <a href="https://console.firebase.google.com/" target="_blank" rel="noopener noreferrer" className="underline font-bold inline-flex items-center gap-0.5 hover:text-amber-600 dark:hover:text-amber-400">Firebase Console <ExternalLink className="w-3 h-3" /></a></div>
                <div>2. Navigate to <strong>Authentication &gt; Sign-in method</strong></div>
                <div>3. Click <strong>Add new provider</strong>, choose <strong>Email/Password</strong>, and enable it.</div>
              </div>
            </div>
          )}

          {/* Actionable Help Banner - Popup Blocked */}
          {error && errorType === "popup-blocked" && (
            <div id="login-popup-error" className="mb-6 p-4 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/50 rounded-xl text-xs text-amber-800 dark:text-amber-300">
              <div className="font-bold flex items-center gap-1.5 text-sm mb-1.5 text-amber-900 dark:text-amber-200">
                <HelpCircle className="w-4 h-4 text-amber-500 shrink-0" />
                <span>Popup Blocked</span>
              </div>
              <p className="leading-relaxed">
                Your browser or the preview iframe sandbox blocked the Google Sign-In popup window.
              </p>
              <div className="mt-2.5 text-[11px] bg-amber-100/50 dark:bg-amber-950/40 p-2.5 rounded border border-amber-200/40">
                💡 <strong>Action:</strong> Click the <strong>"Open in New Tab"</strong> button in the top right corner of the AI Studio preview window to launch the app directly, which allows popups to open successfully!
              </div>
            </div>
          )}

          {/* Simple Alert for other errors */}
          {error && (errorType === "other" || !errorType) && (
            <div id="login-error-alert" className="mb-4 p-3 bg-red-50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/50 rounded-lg text-xs font-semibold text-red-600 dark:text-red-400">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                Email Address
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400">
                  <Mail className="w-4 h-4" />
                </span>
                <input
                  id="login-email-input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none placeholder:text-slate-400 text-slate-800 dark:text-slate-100"
                  placeholder="name@university.edu"
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400">
                  <Lock className="w-4 h-4" />
                </span>
                <input
                  id="login-password-input"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 focus:border-blue-500 dark:focus:border-blue-500 focus:bg-white dark:focus:bg-slate-900 rounded-xl text-sm font-medium transition-all duration-200 outline-none placeholder:text-slate-400 text-slate-800 dark:text-slate-100"
                  placeholder="Minimum 6 characters"
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <button
              id="auth-submit-button"
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-700 active:scale-[0.98] text-white py-3 rounded-xl font-semibold text-sm shadow-md shadow-blue-500/10 flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
            >
              <span>{isSignUp ? "Sign Up" : "Sign In"}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>

          {/* Separator */}
          <div className="my-6 flex items-center justify-center gap-3">
            <span className="w-full h-[1px] bg-slate-100 dark:bg-slate-800"></span>
            <span className="text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">or</span>
            <span className="w-full h-[1px] bg-slate-100 dark:bg-slate-800"></span>
          </div>

          {/* Google Login Button */}
          <button
            id="google-login-button"
            onClick={handleGoogleLogin}
            disabled={loading}
            className="w-full border border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 active:scale-[0.98] bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2.5 transition-all duration-200 cursor-pointer"
          >
            {/* Google Logo vector */}
            <svg className="w-4.5 h-4.5" viewBox="0 0 24 24">
              <path fill="#EA4335" d="M12 5.04c1.62 0 3.08.56 4.22 1.64l3.15-3.15C17.45 1.74 14.93 1 12 1 7.35 1 3.4 3.65 1.5 7.5l3.8 2.94C6.22 7.34 8.87 5.04 12 5.04z" />
              <path fill="#4285F4" d="M23.5 12.25c0-.82-.07-1.61-.21-2.38H12v4.51h6.46c-.28 1.46-1.1 2.69-2.33 3.52l3.63 2.82c2.13-1.97 3.36-4.87 3.36-8.22z" />
              <path fill="#FBBC05" d="M5.3 14.56c-.24-.72-.38-1.49-.38-2.31s.14-1.59.38-2.31L1.5 7.5C.54 9.4 0 11.64 0 14s.54 4.6 1.5 6.5l3.8-2.94z" />
              <path fill="#34A853" d="M12 23c3.24 0 5.97-1.07 7.96-2.91l-3.63-2.82c-1 .67-2.28 1.07-3.63 1.07-3.13 0-5.78-2.3-6.72-5.4l-3.8 2.94C3.4 20.35 7.35 23 12 23z" />
            </svg>
            <span>Continue with Google</span>
          </button>

          {/* Toggle login vs signup */}
          <div className="mt-5 text-center text-xs font-semibold text-slate-500 dark:text-slate-400">
            {isSignUp ? "Already have a profile?" : "Need durable cloud tracking?"}{" "}
            <button
              id="toggle-signup-button"
              type="button"
              onClick={() => setIsSignUp(!isSignUp)}
              className="text-blue-600 dark:text-blue-400 hover:underline hover:text-blue-700 dark:hover:text-blue-300 ml-1 cursor-pointer"
            >
              {isSignUp ? "Sign In" : "Sign Up"}
            </button>
          </div>

          {/* Continue as Guest link */}
          <div className="mt-4 border-t border-slate-100 dark:border-slate-800/80 pt-4 text-center">
            <button
              id="guest-login-button"
              type="button"
              onClick={handleGuestLogin}
              className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 uppercase tracking-widest cursor-pointer group"
            >
              <span>Consult as Guest</span>
              <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
            </button>
          </div>

        </div>
      </div>

    </div>
  );
}

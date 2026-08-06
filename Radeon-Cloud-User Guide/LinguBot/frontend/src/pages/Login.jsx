import React, { useState } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { FiMail, FiLock, FiEye, FiEyeOff, FiCheckCircle, FiAlertTriangle } from 'react-icons/fi';
import { useTheme } from '../context/ThemeContext';
import { HiSun, HiMoon } from 'react-icons/hi2';

const Login = () => {
  const { login } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState('');
  const [serverSuccess, setServerSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  // Parse redirect path from router state
  const from = location.state?.from?.pathname || '/';

  const validate = () => {
    const tempErrors = {};
    if (!email) {
      tempErrors.email = 'Email is required';
    } else if (!/\S+@\S+\.\S+/.test(email)) {
      tempErrors.email = 'Please provide a valid email';
    }
    if (!password) {
      tempErrors.password = 'Password is required';
    } else if (password.length < 6) {
      tempErrors.password = 'Password must be at least 6 characters';
    }
    setErrors(tempErrors);
    return Object.keys(tempErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setServerError('');
    setServerSuccess('');
    
    if (!validate()) return;
    
    setLoading(true);
    const result = await login(email, password);
    setLoading(false);

    if (result.success) {
      setServerSuccess('Authentication successful! Redirecting...');
      setTimeout(() => {
        navigate(from, { replace: true });
      }, 1200);
    } else {
      setServerError(result.error);
    }
  };

  return (
    <div className="flex min-h-screen bg-gray-50 dark:bg-slate-950 relative overflow-hidden transition-colors duration-200">
      {/* Left Column (Illustration) - Only visible on desktop */}
      <div className="hidden lg:flex lg:w-1/2 relative bg-slate-900 dark:bg-slate-950 items-center justify-center p-12 overflow-hidden">
        {/* Abstract Background Gradients */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary-900/40 to-slate-950"></div>
        <div className="absolute -top-45 -left-45 h-96 w-96 rounded-full bg-violet-500/10 blur-3xl"></div>
        
        {/* Content */}
        <div className="relative z-10 max-w-lg text-center space-y-6">
          <img
            src="/hero.jpg"
            alt="LinguaBot Illustration"
            className="w-80 h-80 object-cover rounded-3xl mx-auto shadow-2xl border-4 border-white/10"
          />
          <div>
            <h2 className="text-3xl font-black text-white">Master languages with AI</h2>
            <p className="mt-2 text-sm text-primary-200">
              Practice speaking, verify grammar correctness, translate text in real-time, and challenge yourself with interactive quizzes.
            </p>
          </div>
        </div>
      </div>

      {/* Right Column (Form) */}
      <div className="w-full lg:w-1/2 flex items-center justify-center px-4 py-12 sm:px-6 lg:px-8 relative">
        {/* Dynamic Background Gradients */}
        <div className="absolute -top-40 -left-40 h-80 w-80 rounded-full bg-primary-500/20 blur-3xl dark:bg-primary-950/30"></div>
        <div className="absolute -bottom-40 -right-40 h-80 w-80 rounded-full bg-violet-500/20 blur-3xl dark:bg-violet-950/30"></div>

        {/* Floating Theme Toggle */}
        <button
          onClick={toggleTheme}
          className="absolute top-6 right-6 p-3 rounded-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-300 hover:scale-105 transition shadow-sm z-10"
        >
          {theme === 'dark' ? <HiSun className="h-5 w-5" /> : <HiMoon className="h-5 w-5" />}
        </button>

        <div className="w-full max-w-md space-y-8 glass-panel p-8 rounded-2xl shadow-xl z-10 transition duration-300">
          <div>
            {/* Custom logo */}
            <img src="/logo.jpg" alt="LinguaBot Logo" className="mx-auto h-16 w-16 object-contain rounded-2xl shadow-md border border-gray-100 dark:border-slate-800" />
            <h2 className="mt-6 text-center text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white">
              Welcome back
            </h2>
            <p className="mt-2 text-center text-sm text-gray-600 dark:text-slate-400">
              Log in to continue your language learning journey
            </p>
          </div>

          <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
            {serverError && (
              <div className="flex items-center gap-3 rounded-xl bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900/30 p-4 text-xs text-red-800 dark:text-red-400">
                <FiAlertTriangle className="h-5 w-5 shrink-0" />
                <span>{serverError}</span>
              </div>
            )}

            {serverSuccess && (
              <div className="flex items-center gap-3 rounded-xl bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-900/30 p-4 text-xs text-green-800 dark:text-green-400">
                <FiCheckCircle className="h-5 w-5 shrink-0" />
                <span>{serverSuccess}</span>
              </div>
            )}

            <div className="-space-y-px rounded-md shadow-sm">
              <div className="mb-4">
                <label htmlFor="email-address" className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-1.5 text-left">
                  Email Address
                </label>
                <input
                  id="email-address"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="relative block w-full appearance-none rounded-xl border border-gray-300 dark:border-slate-800 bg-white dark:bg-slate-950 px-3.5 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:z-10 focus:border-primary-500 focus:outline-none focus:ring-primary-500 sm:text-sm"
                  placeholder="name@example.com"
                />
              </div>
              <div>
                <label htmlFor="password" className="block text-xs font-bold text-gray-700 dark:text-slate-350 mb-1.5 text-left">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (errors.password) setErrors({ ...errors, password: '' });
                  }}
                  className={`block w-full rounded-lg border bg-white dark:bg-slate-900 py-3 pl-10 pr-10 text-sm placeholder-gray-400 shadow-sm focus:outline-none focus:ring-2 transition ${
                    errors.password
                      ? 'border-red-300 focus:border-red-500 focus:ring-red-500/20 dark:border-red-800/40'
                      : 'border-gray-300 dark:border-slate-800 focus:border-primary-500 focus:ring-primary-500/20 text-gray-900 dark:text-white'
                  }`}
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
                >
                  {showPassword ? <FiEyeOff /> : <FiEye />}
                </button>
              </div>
              {errors.password && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.password}</p>}
            </div>

          <div>
            <button
              type="submit"
              disabled={loading}
              className="group relative flex w-full justify-center rounded-lg bg-primary-600 py-3 px-4 text-sm font-semibold text-white hover:bg-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/50 active:scale-[0.98] transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-primary-500/10"
            >
              {loading ? (
                <svg className="h-5 w-5 animate-spin text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                'Sign In'
              )}
            </button>
          </div>
        </form>

        <div className="text-center text-sm">
          <span className="text-gray-500 dark:text-slate-400">Don't have an account? </span>
          <Link to="/register" className="font-semibold text-primary-600 hover:text-primary-500 dark:text-primary-400">
            Sign Up
          </Link>
        </div>
      </div>
      </div>
    </div>
  );
};

export default Login;

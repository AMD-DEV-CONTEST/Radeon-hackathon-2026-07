import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { FiMail, FiCheckCircle, FiAlertTriangle, FiArrowLeft } from 'react-icons/fi';
import { useTheme } from '../context/ThemeContext';
import { HiSun, HiMoon } from 'react-icons/hi2';

const ForgotPassword = () => {
  const { forgotPassword } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [email, setEmail] = useState('');
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState('');
  const [serverSuccess, setServerSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const validate = () => {
    const tempErrors = {};
    if (!email) {
      tempErrors.email = 'Email is required';
    } else if (!/\S+@\S+\.\S+/.test(email)) {
      tempErrors.email = 'Please provide a valid email';
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
    const result = await forgotPassword(email);
    setLoading(false);

    if (result.success) {
      setServerSuccess(result.message);
      setEmail('');
    } else {
      setServerError(result.error);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 dark:bg-slate-950 sm:px-6 lg:px-8 relative overflow-hidden transition-colors duration-200">
      {/* Background Gradients */}
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
          <Link
            to="/login"
            className="inline-flex items-center gap-2 text-xs font-semibold text-gray-500 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-400 transition"
          >
            <FiArrowLeft /> Back to login
          </Link>
          <h2 className="mt-6 text-center text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white">
            Forgot password?
          </h2>
          <p className="mt-2 text-center text-sm text-gray-600 dark:text-slate-400">
            No worries! Enter your email and we'll send you reset instructions.
          </p>
        </div>

        {/* Server Success Alert */}
        {serverSuccess && (
          <div className="flex items-center gap-3 rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800/30 p-4 text-sm text-green-800 dark:text-green-400 animate-slide-in">
            <FiCheckCircle className="h-5 w-5 shrink-0" />
            <span>{serverSuccess}</span>
          </div>
        )}

        {/* Server Error Alert */}
        {serverError && (
          <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-800 dark:text-red-400 animate-slide-in">
            <FiAlertTriangle className="h-5 w-5 shrink-0" />
            <span>{serverError}</span>
          </div>
        )}

        <form className="mt-8 space-y-6" onSubmit={handleSubmit} noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 dark:text-slate-300">
              Email Address
            </label>
            <div className="relative mt-1">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-400">
                <FiMail />
              </div>
              <input
                id="email"
                name="email"
                type="email"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (errors.email) setErrors({ ...errors, email: '' });
                }}
                className={`block w-full rounded-lg border bg-white dark:bg-slate-900 py-3 pl-10 pr-3 text-sm placeholder-gray-400 shadow-sm focus:outline-none focus:ring-2 transition ${
                  errors.email
                    ? 'border-red-300 focus:border-red-500 focus:ring-red-500/20 dark:border-red-800/40'
                    : 'border-gray-300 dark:border-slate-800 focus:border-primary-500 focus:ring-primary-500/20 text-gray-900 dark:text-white'
                }`}
                placeholder="name@example.com"
              />
            </div>
            {errors.email && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{errors.email}</p>}
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
                'Send Reset Link'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ForgotPassword;

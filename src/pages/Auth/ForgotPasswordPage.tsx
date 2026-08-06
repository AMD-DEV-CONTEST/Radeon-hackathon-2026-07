import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { Mail, ArrowLeft, Send, Loader2 } from 'lucide-react';

export const ForgotPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const { triggerForgotPassword } = useAuth();

  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      setError('Please provide your email address');
      return;
    }
    setError('');
    setMessage('');
    setSubmitting(true);
    try {
      const msg = await triggerForgotPassword(email);
      setMessage(msg || 'A reset instructions link has been sent to your email.');
    } catch (err: any) {
      setError(err.message || 'Could not verify account email address.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative">
      
      {/* Background glow blobs */}
      <div className="absolute top-[20%] left-[20%] w-[350px] h-[350px] rounded-full bg-primary-600/10 blur-[90px] pointer-events-none" />
      <div className="absolute bottom-[20%] right-[20%] w-[350px] h-[350px] rounded-full bg-cyan-500/10 blur-[90px] pointer-events-none" />

      {/* Main reset container */}
      <div className="w-full max-w-md glass-panel p-8 rounded-2xl border border-dark-800/40 relative shadow-2xl z-10 animate-slide-up">
        
        {/* Brand header */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-12 h-12 bg-gradient-to-tr from-primary-600 to-cyan-500 rounded-2xl flex items-center justify-center text-white font-bold mb-4 shadow-lg shadow-primary-500/20 cursor-pointer" onClick={() => navigate('/')}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="6">
              <path d="M50 15 L58 42 L85 50 L58 58 L50 85 L42 58 L15 50 L42 42 Z" fill="currentColor"/>
            </svg>
          </div>
          <h2 className="font-extrabold text-2xl tracking-tight text-white font-heading">Reset Password</h2>
          <p className="text-xs text-dark-400 mt-1.5 leading-normal max-w-[280px]">Provide your registered email to receive account recovery instructions.</p>
        </div>

        {error && (
          <div className="p-3 bg-rose-950/40 border border-rose-500/30 text-rose-200 text-xs font-semibold rounded-xl mb-6 text-center">
            {error}
          </div>
        )}

        {message ? (
          <div className="flex flex-col gap-6 text-center py-4">
            <div className="p-4 bg-emerald-950/40 border border-emerald-500/30 text-emerald-200 text-xs font-medium rounded-xl leading-relaxed">
              {message}
            </div>
            <button
              onClick={() => navigate('/login')}
              className="px-6 py-3 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 font-bold rounded-xl text-xs flex items-center justify-center gap-2 transition-all"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Login Screen
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            
            {/* Email field */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-dark-300">Email Address</label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-3.5 w-4.5 h-4.5 text-dark-400" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="w-full pl-11 pr-4 py-3 rounded-xl border glass-input text-sm text-dark-100 placeholder:text-dark-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full mt-2 py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl shadow-lg shadow-primary-500/10 hover:shadow-primary-500/20 flex items-center justify-center gap-2 text-sm transition-all hover:scale-102 disabled:opacity-60"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Sending Link...
                </>
              ) : (
                <>
                  Send Recovery Link
                  <Send className="w-4 h-4" />
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => navigate('/login')}
              className="w-full mt-1.5 py-3 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 font-bold rounded-xl text-xs flex items-center justify-center gap-2 transition-all"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Login
            </button>
          </form>
        )}

      </div>
    </div>
  );
};

export default ForgotPasswordPage;

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Compass, ArrowLeft } from 'lucide-react';
import GlassCard from '../components/GlassCard';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex items-center justify-center p-6 relative">
      <div className="absolute top-[30%] left-[30%] w-[300px] h-[300px] rounded-full bg-primary-600/10 blur-[80px] pointer-events-none" />
      <div className="absolute bottom-[30%] right-[30%] w-[300px] h-[300px] rounded-full bg-cyan-500/10 blur-[80px] pointer-events-none" />

      <div className="max-w-md w-full glass-panel p-8 rounded-2xl border border-dark-800/40 text-center relative shadow-2xl z-10 animate-slide-up">
        <div className="p-4 bg-primary-500/10 rounded-full mb-6 text-primary-400 inline-flex relative animate-float">
          <Compass className="w-10 h-10 animate-spin-slow" />
        </div>
        <h1 className="text-4xl font-extrabold font-heading text-dark-50 tracking-tight mb-2">404</h1>
        <h2 className="text-lg font-bold text-dark-200 mb-3">Navigator Lost Course</h2>
        <p className="text-xs text-dark-400 mb-6 leading-relaxed">
          The coordinate page you are looking for has been moved, renamed, or doesn't exist. Click below to return to your dashboard dashboard coordinates.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          className="px-6 py-3 bg-gradient-to-r from-primary-600 to-cyan-600 hover:from-primary-500 hover:to-cyan-500 text-white font-bold rounded-xl text-xs flex items-center justify-center gap-2 transition-all hover:scale-102 mx-auto"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>
      </div>
    </div>
  );
};

export default NotFoundPage;

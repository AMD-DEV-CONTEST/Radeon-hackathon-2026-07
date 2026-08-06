import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';

// Import Layout shell
import Layout from './components/Layout';

// Import Pages
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/Auth/LoginPage';
import SignupPage from './pages/Auth/SignupPage';
import ForgotPasswordPage from './pages/Auth/ForgotPasswordPage';
import DashboardPage from './pages/DashboardPage';
import ResumeAnalyzerPage from './pages/ResumeAnalyzerPage';
import InterviewPrepPage from './pages/InterviewPrepPage';
import SkillGapPage from './pages/SkillGapPage';
import LearningRoadmapPage from './pages/LearningRoadmapPage';
import AIChatPage from './pages/AIChatPage';
import ProfilePage from './pages/ProfilePage';
import SettingsPage from './pages/SettingsPage';
import NotFoundPage from './pages/NotFoundPage';

// Protected Route Shield
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { token, loading } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen bg-dark-950 flex items-center justify-center flex-col gap-3">
        <div className="w-8 h-8 rounded-full border-4 border-t-primary-500 border-r-transparent border-b-transparent border-l-transparent animate-spin" />
        <span className="text-xs font-semibold text-dark-400">Authenticating pilot session...</span>
      </div>
    );
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return <Layout>{children}</Layout>;
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        
        {/* Public Landing & Credentials pages */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />

        {/* Authenticated Dashboard Pages */}
        <Route 
          path="/dashboard" 
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/resume-analyzer" 
          element={
            <ProtectedRoute>
              <ResumeAnalyzerPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/interview" 
          element={
            <ProtectedRoute>
              <InterviewPrepPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/skill-gap" 
          element={
            <ProtectedRoute>
              <SkillGapPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/roadmap" 
          element={
            <ProtectedRoute>
              <LearningRoadmapPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/chat" 
          element={
            <ProtectedRoute>
              <AIChatPage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/profile" 
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          } 
        />
        <Route 
          path="/settings" 
          element={
            <ProtectedRoute>
              <SettingsPage />
            </ProtectedRoute>
          } 
        />

        {/* 404 Routing fallback */}
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />

      </Routes>
    </BrowserRouter>
  );
};

export default App;

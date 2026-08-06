import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ProtectedRoute = ({ children, requiredRole }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center bg-gray-50 dark:bg-slate-950">
        {/* Sleek rotating ring loader */}
        <div className="relative h-16 w-16">
          <div className="absolute h-16 w-16 rounded-full border-4 border-primary-200 dark:border-primary-900"></div>
          <div className="absolute h-16 w-16 animate-spin rounded-full border-4 border-t-primary-600"></div>
        </div>
        <p className="mt-4 text-sm font-semibold text-gray-500 dark:text-slate-400 animate-pulse">
          Verifying secure session...
        </p>
      </div>
    );
  }

  if (!user) {
    // Redirect to login page and save current URL in location state
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (requiredRole && (!user.roles || !user.roles.includes(requiredRole))) {
    // Redirect to default unauthorized or home dashboard
    return <Navigate to="/" replace />;
  }

  return children;
};

export default ProtectedRoute;

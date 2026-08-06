import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';

// Auth Pages
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import Profile from './pages/Profile';

// App Pages
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Grammar from './pages/Grammar';
import Translation from './pages/Translation';
import Quiz from './pages/Quiz';
import Progress from './pages/Progress';
import Admin from './pages/Admin';
import VerifyCertificate from './pages/VerifyCertificate';

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <Routes>
            {/* Public Routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/verify/:code" element={<VerifyCertificate />} />

            {/* Protected Workspace Routes */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              {/* Dashboard */}
              <Route index element={<Dashboard />} />
              
              {/* Profile details */}
              <Route path="profile" element={<Profile />} />

              {/* Core Features */}
              <Route path="chat" element={<Chat />} />
              <Route path="grammar" element={<Grammar />} />
              <Route path="translation" element={<Translation />} />
              <Route path="quiz" element={<Quiz />} />
              <Route path="progress" element={<Progress />} />

              {/* Admin Protected Panel */}
              <Route
                path="admin"
                element={
                  <ProtectedRoute requiredRole="ROLE_ADMIN">
                    <Admin />
                  </ProtectedRoute>
                }
              />
            </Route>

            {/* Fallback Catch-all Route */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;

import React, { createContext, useContext, useState, useEffect } from 'react';
import api from '../services/api';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);

  // Retrieve user details on load if token exists
  useEffect(() => {
    const loadProfile = async () => {
      if (token) {
        try {
          const res = await api.get('/auth/profile');
          setUser(res.data);
        } catch (err) {
          console.error("Failed to load user profile on startup", err);
          // Clean up state if verification fails
          setToken(null);
          setUser(null);
          localStorage.removeItem('token');
        }
      }
      setLoading(false);
    };

    loadProfile();
  }, [token]);

  const login = async (email, password) => {
    setLoading(true);
    try {
      const res = await api.post('/auth/login', { email, password });
      const { token: jwtToken, ...userData } = res.data;
      
      localStorage.setItem('token', jwtToken);
      setToken(jwtToken);
      setUser(userData);
      return { success: true };
    } catch (err) {
      console.error("Login failed:", err);
      const errMsg = err.response?.data?.message || "Invalid credentials. Please try again.";
      return { success: false, error: errMsg };
    } finally {
      setLoading(false);
    }
  };

  const register = async (username, email, password) => {
    setLoading(true);
    try {
      const res = await api.post('/auth/register', { username, email, password });
      return { success: true, message: res.data.message };
    } catch (err) {
      console.error("Registration failed:", err);
      // Try to parse validation details if any
      const validationDetails = err.response?.data?.details;
      let errMsg = err.response?.data?.message || "Registration failed. Please try again.";
      if (validationDetails) {
        errMsg = Object.values(validationDetails).join(", ");
      }
      return { success: false, error: errMsg };
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await api.post('/auth/logout');
    } catch (err) {
      console.warn("Logout request failed on backend, cleaning frontend state anyway", err);
    } finally {
      localStorage.removeItem('token');
      setToken(null);
      setUser(null);
    }
  };

  const forgotPassword = async (email) => {
    try {
      const res = await api.post('/auth/forgot-password', { email });
      return { success: true, message: res.data.message };
    } catch (err) {
      return { success: false, error: err.response?.data?.message || "Failed to submit request." };
    }
  };

  const resetPassword = async (tokenParam, newPassword) => {
    try {
      const res = await api.post('/auth/reset-password', { token: tokenParam, newPassword });
      return { success: true, message: res.data.message };
    } catch (err) {
      return { success: false, error: err.response?.data?.message || "Failed to reset password." };
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        register,
        logout,
        forgotPassword,
        resetPassword,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);

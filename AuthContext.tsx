import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { useNotification } from './NotificationContext';

export interface IAchievement {
  id: string;
  title: string;
  description: string;
  unlockedAt: string;
  icon: string;
}

export interface IUser {
  id: string;
  name: string;
  email: string;
  targetCareer?: string;
  currentSkills: string[];
  theme: 'dark' | 'light';
  language: string;
  achievements: IAchievement[];
}

interface AuthContextType {
  user: IUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  updateProfileSettings: (data: Partial<IUser>) => Promise<void>;
  triggerForgotPassword: (email: string) => Promise<string>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<IUser | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);
  const { showToast } = useNotification();

  // Set auth header helper
  const setAuthHeader = (authToken: string | null) => {
    if (authToken) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${authToken}`;
    } else {
      delete axios.defaults.headers.common['Authorization'];
    }
  };

  // Check auth on mount
  useEffect(() => {
    const initAuth = async () => {
      if (token) {
        setAuthHeader(token);
        try {
          const response = await axios.get('/api/auth/profile');
          setUser(response.data);
        } catch (error) {
          console.error('[Auth Init] Session validation failed:', error);
          logout();
        }
      }
      setLoading(false);
    };
    initAuth();
  }, [token]);

  const login = async (email: string, password: string) => {
    try {
      const response = await axios.post('/api/auth/login', { email, password });
      const { token: userToken, user: userData } = response.data;

      localStorage.setItem('token', userToken);
      setToken(userToken);
      setUser(userData);
      setAuthHeader(userToken);
      showToast(`Welcome back, ${userData.name}!`, 'success');
    } catch (error: any) {
      const msg = error.response?.data?.error || 'Login failed. Invalid credentials.';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  };

  const signup = async (name: string, email: string, password: string) => {
    try {
      const response = await axios.post('/api/auth/signup', { name, email, password });
      const { token: userToken, user: userData } = response.data;

      localStorage.setItem('token', userToken);
      setToken(userToken);
      setUser(userData);
      setAuthHeader(userToken);
      showToast(`Account created! Welcome, ${name}.`, 'success');
      
      // Proactively show achievement toast for signup badge
      setTimeout(() => {
        showToast('You unlocked "Welcome Pilot" badge!', 'achievement', 'Badge Achieved');
      }, 1500);
    } catch (error: any) {
      const msg = error.response?.data?.error || 'Registration failed. Email might be taken.';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
    setAuthHeader(null);
    showToast('Logged out successfully', 'info');
  };

  const refreshProfile = async () => {
    if (!token) return;
    try {
      const response = await axios.get('/api/auth/profile');
      
      // Check if user unlocked a new achievement during this check
      const oldAchievementsCount = user?.achievements.length || 0;
      const newAchievements = response.data.achievements;
      
      if (newAchievements.length > oldAchievementsCount) {
        // Find newly added achievement
        const latest = newAchievements[newAchievements.length - 1];
        showToast(`Unlocked "${latest.title}" Badge!`, 'achievement', 'Milestone Unlocked');
      }

      setUser(response.data);
    } catch (error) {
      console.error('[Auth Refresh] Failed to sync profile stats:', error);
    }
  };

  const updateProfileSettings = async (data: Partial<IUser>) => {
    try {
      const response = await axios.put('/api/auth/profile', data);
      setUser(response.data.user);
      showToast('Settings saved successfully', 'success');
      
      // Refresh profile to pick up any completed achievements
      await refreshProfile();
    } catch (error: any) {
      const msg = error.response?.data?.error || 'Could not update configurations.';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  };

  const triggerForgotPassword = async (email: string): Promise<string> => {
    try {
      const response = await axios.post('/api/auth/forgot-password', { email });
      showToast(response.data.message, 'success');
      return response.data.message;
    } catch (error: any) {
      const msg = error.response?.data?.error || 'Could not check password reset configurations.';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        signup,
        logout,
        updateProfileSettings,
        triggerForgotPassword,
        refreshProfile
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};

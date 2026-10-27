import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

const API_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('askai_user');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authModalTab, setAuthModalTab] = useState('login'); // 'login' | 'register' | 'otp'
  const [pendingEmail, setPendingEmail] = useState('');

  useEffect(() => {
    if (user) {
      localStorage.setItem('askai_user', JSON.stringify(user));
    } else {
      localStorage.removeItem('askai_user');
      localStorage.removeItem('askai_token');
    }
  }, [user]);

  const openAuthModal = (tab = 'login') => {
    setAuthModalTab(tab);
    setIsAuthModalOpen(true);
  };

  const closeAuthModal = () => {
    setIsAuthModalOpen(false);
  };

  // Register
  const register = async (name, email, password) => {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || 'Registration failed');
    }
    setPendingEmail(email);
    setAuthModalTab('otp');
    return data;
  };

  // Verify OTP
  const verifyOtp = async (email, code) => {
    const targetEmail = email || pendingEmail;
    const res = await fetch(`${API_URL}/auth/verify-otp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: targetEmail, code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || 'Verification failed');
    }
    if (data.access_token) {
      localStorage.setItem('askai_token', data.access_token);
    }
    setUser(data.user);
    setIsAuthModalOpen(false);
    return data;
  };

  // Login
  const login = async (email, password) => {
    const res = await fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 403) {
      setPendingEmail(email);
      setAuthModalTab('otp');
      throw new Error(data.detail || 'Please verify your OTP code.');
    }
    if (!res.ok) {
      throw new Error(data.detail || 'Invalid email or password');
    }
    if (data.access_token) {
      localStorage.setItem('askai_token', data.access_token);
    }
    setUser(data.user);
    setIsAuthModalOpen(false);
    return data;
  };

  // Resend OTP
  const resendOtp = async (email) => {
    const targetEmail = email || pendingEmail;
    const res = await fetch(`${API_URL}/auth/resend-otp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: targetEmail }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || 'Failed to resend verification code');
    }
    return data;
  };

  // Logout
  const logout = async () => {
    setUser(null);
    localStorage.removeItem('askai_user');
    localStorage.removeItem('askai_token');
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isAuthModalOpen,
        authModalTab,
        setAuthModalTab,
        pendingEmail,
        setPendingEmail,
        openAuthModal,
        closeAuthModal,
        login,
        register,
        verifyOtp,
        resendOtp,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

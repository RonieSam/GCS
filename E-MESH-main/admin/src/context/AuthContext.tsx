import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client';
import { User } from '../api/types';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isManager: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const handleAuthExpired = () => {
      setUser(null);
    };
    window.addEventListener('emesh:admin_auth_expired', handleAuthExpired);

    const initAuth = async () => {
      const token = localStorage.getItem('emesh_admin_access_token');
      if (token) {
        try {
          const me = await api.getMe();
          setUser(me);
        } catch {
          api.clearTokens();
          setUser(null);
        }
      }
      setLoading(false);
    };

    initAuth();
    return () => window.removeEventListener('emesh:admin_auth_expired', handleAuthExpired);
  }, []);

  const login = async (u: string, p: string) => {
    await api.login(u, p);
    const me = await api.getMe();
    setUser(me);
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  const isAuthenticated = !!user;
  const isAdmin = user?.role === 'ADMIN';
  const isManager = user?.role === 'ADMIN' || user?.role === 'INCIDENT_MANAGER';

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        isAuthenticated,
        isAdmin,
        isManager,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

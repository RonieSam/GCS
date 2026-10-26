import React from 'react';
import { AppLayout } from './components/layout/AppLayout';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LoginView } from './views/LoginView';

const MainContent: React.FC = () => {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div
        className="flex items-center justify-center"
        style={{ minHeight: '100vh', background: '#F2F1EC' }}
      >
        <div className="flex flex-col items-center gap-3">
          <div
            className="pulse-dot online"
            style={{ width: '12px', height: '12px' }}
          />
          <div style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#737A75', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Initializing E-Mesh NOC...
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginView />;
  }

  return <AppLayout />;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <MainContent />
    </AuthProvider>
  );
};

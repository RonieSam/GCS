import React, { useState } from 'react';
import { AlertCircle, Lock, Radio, Shield, User } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const LoginView: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('Admin@Mesh2025');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
    } catch (err: any) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  const setCredentials = (u: string, p: string) => {
    setUsername(u);
    setPassword(p);
  };

  return (
    <div
      className="flex items-center justify-center"
      style={{ minHeight: '100vh', background: '#F2F1EC', padding: '1rem' }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '420px',
          background: '#FFFFFF',
          border: '1px solid #D5D9D4',
          borderRadius: '10px',
          padding: '2rem',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.06)',
        }}
      >
        <div className="flex flex-col items-center text-center mb-6">
          <div
            style={{
              padding: '0.625rem',
              marginBottom: '0.75rem',
              background: 'rgba(113, 137, 166, 0.1)',
              border: '1px solid rgba(113, 137, 166, 0.2)',
              borderRadius: '10px',
            }}
          >
            <Radio size={28} style={{ color: '#7189A6' }} />
          </div>
          <h1 style={{ fontSize: '1.375rem', fontWeight: 800, color: '#343936', letterSpacing: '0.3px' }}>
            E-MESH NOC Admin
          </h1>
          <p style={{ fontSize: '0.75rem', color: '#737A75', marginTop: '0.25rem', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            Emergency Mesh Network Operations
          </p>
        </div>

        {error && (
          <div
            className="flex items-center gap-2"
            style={{
              padding: '0.625rem 0.75rem',
              marginBottom: '1rem',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: '#A06060',
              background: 'rgba(201, 130, 130, 0.08)',
              border: '1px solid rgba(201, 130, 130, 0.2)',
              borderRadius: '6px',
            }}
          >
            <AlertCircle size={15} className="flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label flex items-center gap-1\.5">
              <User size={13} style={{ color: '#7189A6' }} /> Username
            </label>
            <input
              type="text"
              required
              className="form-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. admin"
            />
          </div>

          <div className="form-group">
            <label className="form-label flex items-center gap-1\.5">
              <Lock size={13} style={{ color: '#7189A6' }} /> Password
            </label>
            <input
              type="password"
              required
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary w-full"
            style={{ padding: '0.625rem', marginTop: '0.25rem' }}
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid #D5D9D4' }}>
          <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#9AA09B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem', textAlign: 'center' }}>
            Quick Access Profiles
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setCredentials('admin', 'Admin@Mesh2025')}
              style={{ fontSize: '0.6875rem' }}
            >
              <Shield size={12} style={{ color: '#D8B878' }} /> System Admin
            </button>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setCredentials('manager', 'Manager@Mesh2025')}
              style={{ fontSize: '0.6875rem' }}
            >
              <User size={12} style={{ color: '#7189A6' }} /> Manager
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

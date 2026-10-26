import React, { useEffect, useState } from 'react';
import { LogOut, Menu, Radio, User as UserIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

interface HeaderProps {
  onMobileMenuToggle: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onMobileMenuToggle }) => {
  const { user, logout } = useAuth();
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="app-header glass-surface">
      <div className="flex items-center gap-3">
        <button className="mobile-menu-btn" onClick={onMobileMenuToggle} title="Toggle navigation">
          <Menu size={18} />
        </button>

        <div
          className="flex items-center gap-2"
          style={{
            padding: '4px 8px',
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-full)',
          }}
        >
          <span className="pulse-dot online" />
          <span className="text-xs font-semibold uppercase tracking-wider text-emerald">
            Gateway Online
          </span>
          <span className="text-xs text-dim">| Sim-Mesh</span>
        </div>

        <div className="hidden md:flex items-center gap-2 text-xs font-mono text-muted">
          <Radio size={12} className="text-blue" />
          <span>FREQ: 2.4 GHz (ESP-NOW)</span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="hidden sm:block text-xs font-mono text-muted">
          <span className="text-dim">SYS TIME:</span> {timeStr}
        </div>

        <div className="flex items-center gap-3" style={{ paddingLeft: '12px', borderLeft: '1px solid var(--border-subtle)' }}>
          <div className="flex items-center gap-2">
            <div
              className="flex items-center justify-center shrink-0"
              style={{
                width: '28px',
                height: '28px',
                background: 'var(--bg-surface-elevated)',
                borderRadius: '50%',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <UserIcon size={14} className="text-blue" />
            </div>
            <div>
              <div className="text-sm font-semibold leading-none text-main">
                {user?.full_name || user?.username}
              </div>
              <div className="text-xs text-dim mt-1 leading-none">
                {user?.role}
              </div>
            </div>
          </div>

          <button onClick={logout} className="btn-icon" title="Sign out of NOC">
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </header>
  );
};

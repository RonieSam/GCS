import React, { useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Cpu,
  FileText,
  Layers,
  MapPin,
  Megaphone,
  Network,
  Radio,
  Settings,
  Shield,
  Users,
} from 'lucide-react';

export type ActiveTab =
  | 'dashboard'
  | 'incidents'
  | 'sos'
  | 'topology'
  | 'nodes'
  | 'responders'
  | 'people'
  | 'resources'
  | 'announcements'
  | 'analytics'
  | 'network-analytics'
  | 'heatmap'
  | 'community'
  | 'audit'
  | 'settings';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  activeSosCount: number;
  activeIncidentCount: number;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const navSections = [
  {
    label: 'Operations',
    items: [
      { id: 'dashboard' as ActiveTab, label: 'Dashboard', icon: Activity },
      {
        id: 'sos' as ActiveTab,
        label: 'Emergency SOS',
        icon: AlertOctagon,
        badgeKey: 'sos' as const,
      },
      {
        id: 'incidents' as ActiveTab,
        label: 'Incidents',
        icon: AlertTriangle,
        badgeKey: 'incidents' as const,
      },
      { id: 'topology' as ActiveTab, label: 'Network Map', icon: Network },
      { id: 'heatmap' as ActiveTab, label: 'People Heatmap', icon: MapPin },
    ],
  },
  {
    label: 'Infrastructure',
    items: [
      { id: 'nodes' as ActiveTab, label: 'Devices', icon: Cpu },
      { id: 'responders' as ActiveTab, label: 'Responders', icon: Shield },
      { id: 'people' as ActiveTab, label: 'People', icon: Users },
      { id: 'community' as ActiveTab, label: 'Community', icon: Radio },
      { id: 'resources' as ActiveTab, label: 'Resources', icon: Boxes },
      { id: 'announcements' as ActiveTab, label: 'Broadcasts', icon: Megaphone },
    ],
  },
  {
    label: 'Administration',
    items: [
      { id: 'analytics' as ActiveTab, label: 'Reports', icon: Layers },
      { id: 'network-analytics' as ActiveTab, label: 'Monitoring', icon: Activity },
      { id: 'audit' as ActiveTab, label: 'Audit Logs', icon: FileText },
      { id: 'settings' as ActiveTab, label: 'Settings', icon: Settings },
    ],
  },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  activeSosCount,
  activeIncidentCount,
  mobileOpen,
  onMobileClose,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const getBadge = (key?: 'sos' | 'incidents') => {
    if (key === 'sos' && activeSosCount > 0) return activeSosCount;
    if (key === 'incidents' && activeIncidentCount > 0) return activeIncidentCount;
    return undefined;
  };

  const handleNavClick = (tab: ActiveTab) => {
    setActiveTab(tab);
    onMobileClose();
  };

  const sidebarClasses = [
    'app-sidebar',
    'glass-panel',
    collapsed ? 'collapsed' : '',
    mobileOpen ? 'mobile-open' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <aside className={sidebarClasses}>
      <div className="sidebar-header">
        <div
          className="flex items-center justify-center shrink-0"
          style={{
            padding: '6px',
            background: 'var(--bg-card)',
            borderRadius: '6px',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <Radio size={16} style={{ color: 'var(--accent-primary)' }} />
        </div>
        <div className="sidebar-brand-text">
          <div className="text-sm font-bold text-main leading-tight tracking-tight">
            E-MESH NOC
          </div>
          <div className="text-xs text-muted leading-tight">
            Admin Panel
          </div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navSections.map((section, sIdx) => (
          <React.Fragment key={section.label}>
            {sIdx > 0 && <div style={{ height: '8px' }} />}
            <div className="sidebar-section-label">{section.label}</div>
            {section.items.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              const badge = getBadge((item as any).badgeKey);
              return (
                <button
                  key={item.id}
                  className={`nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => handleNavClick(item.id)}
                  title={collapsed ? item.label : undefined}
                >
                  <div className="flex items-center gap-3">
                    <Icon
                      size={16}
                      style={{
                        color: isActive ? 'var(--accent-primary)' : 'var(--text-muted)',
                        flexShrink: 0,
                      }}
                    />
                    <span className="nav-label">{item.label}</span>
                  </div>
                  {badge !== undefined && <span className="nav-item-badge">{badge}</span>}
                  <span className="nav-item-tooltip">{item.label}</span>
                </button>
              );
            })}
          </React.Fragment>
        ))}
      </nav>

      <button
        className="sidebar-collapse-btn"
        onClick={() => setCollapsed(!collapsed)}
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>
    </aside>
  );
};

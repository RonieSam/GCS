import React, { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { AnalyticsView } from '../../views/AnalyticsView';
import { AnnouncementsView } from '../../views/AnnouncementsView';
import { AuditLogView } from '../../views/AuditLogView';
import { CommunityView } from '../../views/CommunityView';
import { DashboardView } from '../../views/DashboardView';
import { HeatmapView } from '../../views/HeatmapView';
import { IncidentsView } from '../../views/IncidentsView';
import { NetworkAnalyticsView } from '../../views/NetworkAnalyticsView';
import { NodesView } from '../../views/NodesView';
import { PeopleView } from '../../views/PeopleView';
import { RespondersView } from '../../views/RespondersView';
import { ResourcesView } from '../../views/ResourcesView';
import { SOSQueueView } from '../../views/SOSQueueView';
import { SystemSettingsView } from '../../views/SystemSettingsView';
import { TopologyView } from '../../views/TopologyView';
import { Header } from './Header';
import { ActiveTab, Sidebar } from './Sidebar';
import { useMeshEvent } from '../../api/ws';

export const AppLayout: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('dashboard');
  const [activeSosCount, setActiveSosCount] = useState(0);
  const [activeIncidentCount, setActiveIncidentCount] = useState(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const fetchBadgeCounts = async () => {
    try {
      const summary = await api.getAnalyticsSummary();
      setActiveSosCount(summary.sos.active);
      setActiveIncidentCount(summary.incidents.active);
    } catch {
      // ignore offline badge poll
    }
  };

  useEffect(() => {
    fetchBadgeCounts();
  }, []);

  useMeshEvent('sos.created', () => fetchBadgeCounts());
  useMeshEvent('incident.created', () => fetchBadgeCounts());
  useMeshEvent('incident.updated', () => fetchBadgeCounts());
  useMeshEvent('incident.resolved', () => fetchBadgeCounts());

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardView setActiveTab={setActiveTab} />;
      case 'incidents':
        return <IncidentsView />;
      case 'sos':
        return <SOSQueueView />;
      case 'topology':
        return <TopologyView />;
      case 'heatmap':
        return <HeatmapView />;
      case 'nodes':
        return <NodesView />;
      case 'responders':
        return <RespondersView />;
      case 'people':
        return <PeopleView />;
      case 'community':
        return <CommunityView />;
      case 'resources':
        return <ResourcesView />;
      case 'announcements':
        return <AnnouncementsView />;
      case 'analytics':
        return <AnalyticsView />;
      case 'network-analytics':
        return <NetworkAnalyticsView />;
      case 'audit':
        return <AuditLogView />;
      case 'settings':
        return <SystemSettingsView />;
      default:
        return <DashboardView setActiveTab={setActiveTab} />;
    }
  };

  return (
    <div className="app-container">
      {mobileMenuOpen && (
        <div className="sidebar-overlay" onClick={() => setMobileMenuOpen(false)} />
      )}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        activeSosCount={activeSosCount}
        activeIncidentCount={activeIncidentCount}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
      />
      <div className="app-main">
        <Header onMobileMenuToggle={() => setMobileMenuOpen(!mobileMenuOpen)} />
        <main className="app-content">{renderContent()}</main>
      </div>
    </div>
  );
};

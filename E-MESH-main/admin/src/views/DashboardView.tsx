import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  BatteryCharging,
  Cpu,
  Megaphone,
  Radio,
  RefreshCw,
  Shield,
  Zap,
  ActivitySquare,
  Network
} from 'lucide-react';
import { api } from '../api/client';
import { AnalyticsSummary, Incident, SOS } from '../api/types';
import { ActiveTab } from '../components/layout/Sidebar';

import { useMeshEvent } from '../api/ws';

interface DashboardViewProps {
  setActiveTab: (tab: ActiveTab) => void;
  onSelectIncident?: (id: string) => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({ setActiveTab }) => {
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [activeSOSList, setActiveSOSList] = useState<SOS[]>([]);
  const [recentIncidents, setRecentIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    setLoading(true);
    try {
      const [stats, sosResp, incResp] = await Promise.all([
        api.getAnalyticsSummary(),
        api.getSOSList({ status: 'ACTIVE', page_size: 5 }),
        api.getIncidents({ page_size: 5 }),
      ]);
      setAnalytics(stats);
      setActiveSOSList(sosResp.data);
      setRecentIncidents(incResp.data);
    } catch (err) {
      console.error('Failed to fetch dashboard data', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useMeshEvent('sos.created', () => loadData());
  useMeshEvent('incident.created', () => loadData());
  useMeshEvent('incident.updated', () => loadData());
  useMeshEvent('incident.resolved', () => loadData());
  useMeshEvent('node.online', () => loadData());
  useMeshEvent('node.offline', () => loadData());

  const hasSOS = activeSOSList.length > 0;

  return (
    <div className="space-y-4">
      {/* Header Area */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <h2 className="text-2xl font-bold text-main leading-tight">Dashboard Overview</h2>
          <p className="text-sm text-muted mt-1">Network status and active field operations</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-mono">Last updated: Just now</span>
          </div>
          <button onClick={loadData} disabled={loading} className="btn btn-sm">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* Critical SOS Strip */}
      {hasSOS && (
        <div className="widget" style={{ borderLeft: '4px solid var(--accent-red)', background: 'rgba(201, 130, 130, 0.04)' }}>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center rounded-full bg-red text-white" style={{ width: '32px', height: '32px' }}>
                <AlertOctagon size={16} />
              </div>
              <div>
                <div className="text-sm font-bold text-red uppercase tracking-wider">
                  Critical SOS Alert ({activeSOSList.length} Active)
                </div>
                <div className="text-xs text-muted mt-1">
                  Immediate dispatch required for {activeSOSList.reduce((acc, s) => acc + s.people_count, 0)} personnel.
                </div>
              </div>
            </div>
            <button onClick={() => setActiveTab('sos')} className="btn btn-danger btn-sm">
              Triage Queue <ArrowRight size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Top Status Strip (Small Widgets) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1 */}
        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-red)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><AlertOctagon size={12} className="text-red"/> Active SOS</div>
              <div className="metric-value font-mono text-red">{analytics?.sos.active ?? 0}</div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.sos.total ?? 0} total logged</span>
            <span className="font-semibold text-red">Max Priority</span>
          </div>
        </div>

        {/* Metric 2 */}
        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-amber)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><AlertTriangle size={12} className="text-amber"/> Incidents</div>
              <div className="metric-value font-mono text-amber">{analytics?.incidents.active ?? 0}</div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.incidents.resolved ?? 0} resolved today</span>
            <span className="font-semibold text-amber">Triage Required</span>
          </div>
        </div>

        {/* Metric 3 */}
        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-emerald)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Radio size={12} className="text-emerald"/> Mesh Nodes</div>
              <div className="metric-value font-mono text-main">
                {analytics?.mesh.online_nodes ?? 0} <span className="text-lg text-dim">/ {analytics?.mesh.total_nodes ?? 0}</span>
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>Health: {analytics?.mesh.health_pct ?? 100}%</span>
            <span className="flex items-center gap-1 font-semibold text-emerald"><BatteryCharging size={10} /> {analytics?.mesh.avg_battery_pct ?? 100}%</span>
          </div>
        </div>

        {/* Metric 4 */}
        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-blue)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Shield size={12} className="text-blue"/> Responders</div>
              <div className="metric-value font-mono text-main">
                {analytics?.responders.available ?? 0} <span className="text-lg text-dim">Avail</span>
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.responders.deployed ?? 0} deployed</span>
            <span>{analytics?.responders.total ?? 0} total</span>
          </div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        
        {/* Left Large Column (Network Health & Quick Actions) */}
        <div className="lg:col-span-8 space-y-4">
          <div className="widget" style={{ minHeight: '320px' }}>
            <div className="widget-header border-b border-subtle pb-3 mb-4">
              <div className="widget-title"><Network size={16}/> Mesh Network Health</div>
              <button onClick={() => setActiveTab('topology')} className="btn btn-sm">View Map</button>
            </div>
            
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                <div className="text-xs text-muted mb-1">Tree Depth</div>
                <div className="text-xl font-bold font-mono text-main">4 Layers</div>
              </div>
              <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                <div className="text-xs text-muted mb-1">Root Node</div>
                <div className="text-xl font-bold font-mono text-emerald">GATEWAY</div>
              </div>
              <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                <div className="text-xs text-muted mb-1">Packet Loss</div>
                <div className="text-xl font-bold font-mono text-main">0.4%</div>
              </div>
            </div>

            <div className="flex-1 bg-app border border-subtle rounded-sm flex items-center justify-center text-muted text-sm relative overflow-hidden p-4">
              {/* Abstract visualization of network health */}
              <div className="absolute inset-0 opacity-10" style={{ background: 'repeating-linear-gradient(45deg, var(--accent-primary) 0, var(--accent-primary) 1px, transparent 1px, transparent 16px)' }} />
              <div className="relative z-10 flex flex-col items-center gap-2">
                <Radio size={32} className="text-emerald opacity-80" />
                <span className="font-mono text-xs uppercase tracking-widest text-main">Topology Stable</span>
                <span className="text-xs text-dim text-center max-w-xs">Routing tree optimized. No significant congestion detected in application payload stream.</span>
              </div>
            </div>
          </div>

          {/* Quick Actions Panel */}
          <div className="widget">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 shrink-0 border-r border-subtle pr-4">
                <Zap size={14} className="text-amber" />
                <span className="text-xs font-bold uppercase tracking-widest text-main">Actions</span>
              </div>
              <div className="flex items-center gap-2 overflow-x-auto flex-1">
                <button onClick={() => setActiveTab('announcements')} className="btn btn-sm">
                  <Megaphone size={12} className="text-amber" /> Broadcast
                </button>
                <button onClick={() => setActiveTab('responders')} className="btn btn-sm">
                  <Shield size={12} className="text-blue" /> Dispatch
                </button>
                <button onClick={() => setActiveTab('nodes')} className="btn btn-sm">
                  <Cpu size={12} className="text-cyan" /> Configure Node
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Medium Column (Recent Incidents) */}
        <div className="lg:col-span-4 flex flex-col space-y-4">
          <div className="widget flex-1" style={{ minHeight: '384px' }}>
            <div className="widget-header border-b border-subtle pb-3 mb-0">
              <div className="widget-title"><ActivitySquare size={16}/> Active Incidents</div>
              <button onClick={() => setActiveTab('incidents')} className="text-xs font-semibold text-blue hover:underline">View All</button>
            </div>
            
            <div className="flex-1 overflow-y-auto">
              {recentIncidents.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-muted p-6 text-center gap-2">
                  <Activity size={24} className="opacity-20" />
                  <span className="text-xs font-medium">No recent incidents reported.</span>
                </div>
              ) : (
                <div className="flex flex-col">
                  {recentIncidents.map((incident, idx) => (
                    <div 
                      key={incident.incident_id} 
                      className={`p-3 border-b border-subtle flex flex-col gap-2 hover:bg-surface-elevated transition-colors cursor-pointer ${idx === recentIncidents.length -1 ? 'border-b-0' : ''}`}
                      onClick={() => setActiveTab('incidents')}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-bold text-main">{incident.incident_id}</span>
                        <span className={`badge ${incident.priority === 'CRITICAL' ? 'badge-red' : incident.priority === 'HIGH' ? 'badge-amber' : 'badge-blue'}`}>
                          {incident.priority}
                        </span>
                      </div>
                      <div className="text-sm font-medium text-main leading-tight truncate">
                        {incident.category.replace(/_/g, ' ')} — {incident.description.slice(0, 60)}{incident.description.length > 60 ? '…' : ''}
                      </div>
                      <div className="flex items-center justify-between mt-1">
                        <div className="text-xs text-muted flex items-center gap-1">
                          <AlertTriangle size={10} /> {incident.category}
                        </div>
                        <div className="text-xs text-dim font-mono">
                          {new Date(incident.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};

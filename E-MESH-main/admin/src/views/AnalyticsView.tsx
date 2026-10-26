import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Battery,
  Boxes,
  Cpu,
  Layers,
  RefreshCw,
  Shield,
  Users,
} from 'lucide-react';
import { api } from '../api/client';
import { AnalyticsSummary } from '../api/types';

export const AnalyticsView: React.FC = () => {
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await api.getAnalyticsSummary();
      setAnalytics(data);
    } catch (err) {
      console.error('Failed to load analytics', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Analytics & KPIs</h2>
          <p className="text-sm text-muted mt-1">
            Historical aggregates and system performance metrics
          </p>
        </div>

        <button onClick={loadData} disabled={loading} className="btn">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh Metrics
        </button>
      </div>

      {/* Primary KPI row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-blue)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Shield size={12} className="text-blue"/> Clearance Rate</div>
              <div className="metric-value font-mono text-blue">
                {analytics?.incidents.total
                  ? Math.round((analytics.incidents.resolved / analytics.incidents.total) * 100)
                  : 100}%
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.incidents.resolved ?? 0} resolved of {analytics?.incidents.total ?? 0}</span>
          </div>
        </div>

        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-red)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Activity size={12} className="text-red"/> Distress Res.</div>
              <div className="metric-value font-mono text-red">
                {analytics?.sos.total
                  ? Math.round(((analytics.sos.total - analytics.sos.active) / analytics.sos.total) * 100)
                  : 100}%
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.sos.active ?? 0} pending action</span>
          </div>
        </div>

        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-emerald)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Layers size={12} className="text-emerald"/> Mesh Uptime</div>
              <div className="metric-value font-mono text-emerald">
                {analytics?.mesh.health_pct ?? 100}%
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.mesh.online_nodes ?? 0} Relays Active</span>
          </div>
        </div>

        <div className="metric-widget" style={{ borderTop: '3px solid var(--accent-amber)' }}>
          <div className="flex justify-between items-start">
            <div>
              <div className="metric-label uppercase tracking-widest text-muted"><Users size={12} className="text-amber"/> Mobilization</div>
              <div className="metric-value font-mono text-amber">
                {analytics?.responders.total
                  ? Math.round((analytics.responders.deployed / analytics.responders.total) * 100)
                  : 0}%
              </div>
            </div>
          </div>
          <div className="metric-subtext">
            <span>{analytics?.responders.deployed ?? 0} deployed in field</span>
          </div>
        </div>
      </div>

      {/* Category Breakdown & Performance Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="widget" style={{ minHeight: '320px' }}>
          <div className="widget-header border-b border-subtle pb-3 mb-4">
            <div className="flex items-center gap-2 font-bold text-main">
              <AlertTriangle size={16} className="text-amber" /> Incident Breakdown
            </div>
          </div>

          {Object.keys(analytics?.incidents.by_category || {}).length === 0 ? (
            <div className="text-center py-8 text-muted text-sm flex flex-col items-center gap-2">
              <Boxes size={24} className="opacity-30" /> No incidents recorded yet.
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(analytics?.incidents.by_category || {}).map(([cat, count]) => {
                const total = analytics?.incidents.total || 1;
                const pct = Math.round((count / total) * 100);
                return (
                  <div key={cat}>
                    <div className="flex justify-between text-xs font-semibold mb-1">
                      <span className="text-main">{cat.replace(/_/g, ' ')}</span>
                      <span className="font-mono text-blue">{count} ({pct}%)</span>
                    </div>
                    <div className="w-full bg-surface-elevated rounded-full h-1.5 overflow-hidden">
                      <div className="bg-blue h-full rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="widget" style={{ minHeight: '320px' }}>
          <div className="widget-header border-b border-subtle pb-3 mb-4">
            <div className="flex items-center gap-2 font-bold text-main">
              <Cpu size={16} className="text-emerald" /> Hardware Telemetry
            </div>
          </div>

          <div className="space-y-6">
            <div className="p-4 bg-app rounded-sm border border-subtle">
              <div className="flex justify-between text-sm font-bold text-main mb-2">
                <span>Average Mesh Battery Level</span>
                <span className="text-emerald font-mono">{analytics?.mesh.avg_battery_pct ?? 100}%</span>
              </div>
              <div className="w-full bg-surface rounded-full h-2 overflow-hidden border border-subtle">
                <div className="bg-emerald h-full" style={{ width: `${analytics?.mesh.avg_battery_pct ?? 100}%` }} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-surface-elevated rounded-sm border border-subtle">
                <div className="text-xs font-bold text-muted uppercase tracking-widest mb-1">Network Relays</div>
                <div className="text-3xl font-mono font-bold text-main">{analytics?.mesh.total_nodes ?? 0}</div>
              </div>
              <div className="p-4 bg-surface-elevated rounded-sm border border-subtle">
                <div className="text-xs font-bold text-muted uppercase tracking-widest mb-1">Field Devices</div>
                <div className="text-3xl font-mono font-bold text-blue">{analytics?.users.total ?? 0}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

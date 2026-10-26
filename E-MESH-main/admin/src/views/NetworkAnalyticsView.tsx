import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  Clock,
  Cpu,
  Layers,
  Network,
  Power,
  Radio,
  RefreshCw,
  RotateCcw,
  Route,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Wifi,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { AnalyticsMetrics, SimulatedNode, TimelineEvent } from '../api/types';
import { useMeshEvent } from '../api/ws';

export const NetworkAnalyticsView: React.FC = () => {
  const [metrics, setMetrics] = useState<AnalyticsMetrics | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [nodes, setNodes] = useState<SimulatedNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  // Failure Simulation Form State
  const [selectedParentId, setSelectedParentId] = useState<string>('EM-01');
  const [selectedNodeOfflineId, setSelectedNodeOfflineId] = useState<string>('EM-03');
  const [degradeSrc, setDegradeSrc] = useState<string>('EM-01');
  const [degradeDst, setDegradeDst] = useState<string>('EM-04');
  const [degradeLoss, setDegradeLoss] = useState<number>(65);
  const [degradeLatency, setDegradeLatency] = useState<number>(140);

  const loadData = async () => {
    setLoading(true);
    try {
      const [m, tl, n] = await Promise.all([
        api.getSimulationAnalytics(),
        api.getSimulationTimeline(40),
        api.getSimulationNodes(),
      ]);
      setMetrics(m);
      setTimeline(tl);
      setNodes(n);
    } catch (err) {
      console.error('Failed to load network analytics', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useMeshEvent('simulation.updated', () => loadData());
  useMeshEvent('simulation.event', () => loadData());
  useMeshEvent('node.offline', () => loadData());
  useMeshEvent('node.online', () => loadData());

  const showFeedback = (msg: string) => {
    setActionFeedback(msg);
    setTimeout(() => setActionFeedback(null), 4000);
  };

  const handleSimulateParentFailure = async () => {
    try {
      await api.failSimulationParent({ parent_node_id: selectedParentId, auto_reheal: true });
      showFeedback(`Simulated parent failure on ${selectedParentId}`);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleToggleNodeOffline = async () => {
    try {
      await api.takeSimulationNodeOffline(selectedNodeOfflineId);
      showFeedback(`Took ${selectedNodeOfflineId} offline`);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleSimulateGatewayFailure = async () => {
    if (!confirm('WARNING: Simulating Gateway failure will trigger a full mesh partition and force all nodes into ISOLATED mode. Proceed?')) return;
    try {
      await api.failSimulationGateway();
      showFeedback('Gateway crash simulated');
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleRestoreFullNetwork = async () => {
    try {
      await api.restoreSimulationNetwork();
      showFeedback('Full network restoration triggered');
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDegradeLink = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.degradeSimulationLink({
        source_node_id: degradeSrc,
        target_node_id: degradeDst,
        packet_loss_percent: degradeLoss,
        latency_ms: degradeLatency,
      });
      showFeedback(`Link degraded: ${degradeSrc} -> ${degradeDst}`);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity size={20} className="text-primary" />
            <h2 className="text-xl font-bold text-main leading-tight">Network Analytics</h2>
          </div>
          <p className="text-sm text-muted mt-1">
            Application-level simulator, self-healing tree reconfiguration, and recovery telemetry
          </p>
        </div>

        <div className="flex items-center gap-3">
          {actionFeedback && (
            <span className="text-xs font-mono text-emerald bg-emerald/10 px-2 py-1 rounded-sm border border-emerald/20 animate-in fade-in">
              ✓ {actionFeedback}
            </span>
          )}
          <button onClick={handleRestoreFullNetwork} className="btn btn-primary">
            <RotateCcw size={14} /> Reset Network
          </button>
          <button onClick={loadData} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      {metrics && (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
          <div className="metric-widget border-t-2 border-emerald">
            <div className="metric-label uppercase tracking-widest text-muted">Node Availability</div>
            <div className="text-2xl font-bold font-mono text-emerald mt-2">
              {metrics.node_availability_percent}%
            </div>
            <div className="text-xs text-muted mt-1 font-mono">
              {metrics.online_nodes} / {metrics.total_nodes} ONLINE
            </div>
            <div className="w-full bg-surface rounded-full h-1 mt-3 overflow-hidden">
              <div className="bg-emerald h-full" style={{ width: `${metrics.node_availability_percent}%` }} />
            </div>
          </div>

          <div className="metric-widget border-t-2 border-blue">
            <div className="metric-label uppercase tracking-widest text-muted">Delivery Ratio</div>
            <div className="text-2xl font-bold font-mono text-blue mt-2">
              {metrics.packet_delivery_ratio}%
            </div>
            <div className="text-xs text-muted mt-1 font-mono">
              Loss: {metrics.packet_loss_percent}%
            </div>
          </div>

          <div className="metric-widget border-t-2 border-gray">
            <div className="metric-label uppercase tracking-widest text-muted">Avg Latency</div>
            <div className="text-2xl font-bold font-mono text-main mt-2">
              {metrics.average_latency_ms} <span className="text-sm text-muted">ms</span>
            </div>
            <div className="text-xs text-muted mt-1">End-to-end multi-hop</div>
          </div>

          <div className="metric-widget border-t-2 border-gray">
            <div className="metric-label uppercase tracking-widest text-muted">Avg Hop Count</div>
            <div className="text-2xl font-bold font-mono text-main mt-2">
              {metrics.average_hop_count} <span className="text-sm text-muted">hops</span>
            </div>
            <div className="text-xs text-muted mt-1">To Root Gateway</div>
          </div>

          <div className="metric-widget border-t-2 border-amber">
            <div className="metric-label uppercase tracking-widest text-muted">Topology Changes</div>
            <div className="text-2xl font-bold font-mono text-amber mt-2">
              {metrics.topology_changes_count}
            </div>
            <div className="text-xs text-muted mt-1">Self-healing events</div>
          </div>

          <div className="metric-widget border-t-2 border-emerald" style={{ background: 'rgba(136, 179, 148, 0.05)' }}>
            <div className="metric-label uppercase tracking-widest text-emerald font-bold">Latest Recovery</div>
            <div className="text-2xl font-bold font-mono text-emerald mt-2">
              {metrics.latest_recovery_time_ms} <span className="text-sm text-emerald/60">ms</span>
            </div>
            <div className="text-xs text-emerald/80 mt-1">Avg: {metrics.average_recovery_time_ms}ms</div>
          </div>
        </div>
      )}

      {/* Recovery Time Formula Visualizer */}
      <div className="widget bg-surface">
        <div className="flex flex-wrap items-center gap-4">
          <div className="p-2 rounded-sm bg-blue/10 text-blue shrink-0">
            <Clock size={20} />
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-widest text-main mb-1">
              Recovery Time Metric Definition
            </div>
            <div className="text-xs font-mono text-primary bg-surface-elevated p-2 rounded-sm border border-subtle inline-block">
              recovery_time = Timestamp(Communication Re-established) − Timestamp(Failure Detected)
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Event Simulation Controls */}
        <div className="lg:col-span-5 space-y-4">
          <div className="widget" style={{ minHeight: '380px' }}>
            <div className="widget-header border-b border-subtle pb-3 mb-4">
              <div className="text-sm font-bold text-main flex items-center gap-2">
                <ShieldAlert size={16} className="text-amber" /> Network Disruption Controls
              </div>
            </div>

            <div className="space-y-6">
              {/* Force Gateway Offline */}
              <div className="flex items-center justify-between p-3 border border-red/30 bg-red/5 rounded-sm">
                <div>
                  <div className="text-sm font-bold text-red mb-1">Simulate Gateway Crash</div>
                  <div className="text-xs text-red/80">Forces all nodes into isolated mode instantly.</div>
                </div>
                <button onClick={handleSimulateGatewayFailure} className="btn btn-sm btn-danger">Crash Gateway</button>
              </div>

              {/* Force Node Offline */}
              <div className="p-3 border border-subtle bg-surface-elevated rounded-sm">
                <div className="text-sm font-bold text-main mb-2">Simulate Hardware Failure</div>
                <div className="flex gap-2">
                  <select
                    className="form-select flex-1"
                    value={selectedParentId}
                    onChange={(e) => setSelectedParentId(e.target.value)}
                  >
                    {nodes.filter(n => n.node_id !== 'GATEWAY').map(n => (
                      <option key={n.node_id} value={n.node_id}>{n.node_id} (Layer {n.layer})</option>
                    ))}
                  </select>
                  <button onClick={handleSimulateParentFailure} className="btn btn-sm">Kill Node</button>
                </div>
              </div>

              {/* Degrade Link */}
              <form onSubmit={handleDegradeLink} className="p-3 border border-subtle bg-surface-elevated rounded-sm">
                <div className="text-sm font-bold text-main mb-2">Simulate Link Degradation</div>
                
                <div className="flex items-center gap-2 mb-3">
                  <select className="form-select flex-1" value={degradeSrc} onChange={(e) => setDegradeSrc(e.target.value)}>
                    {nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.node_id}</option>)}
                  </select>
                  <ArrowRight size={14} className="text-muted shrink-0" />
                  <select className="form-select flex-1" value={degradeDst} onChange={(e) => setDegradeDst(e.target.value)}>
                    {nodes.map(n => <option key={n.node_id} value={n.node_id}>{n.node_id}</option>)}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="form-label">Packet Loss (%)</label>
                    <input type="number" min="0" max="100" className="form-input" value={degradeLoss} onChange={(e) => setDegradeLoss(parseInt(e.target.value))} />
                  </div>
                  <div>
                    <label className="form-label">Latency (ms)</label>
                    <input type="number" min="0" max="5000" className="form-input" value={degradeLatency} onChange={(e) => setDegradeLatency(parseInt(e.target.value))} />
                  </div>
                </div>

                <button type="submit" className="btn btn-sm w-full justify-center">Degrade Connection</button>
              </form>
            </div>
          </div>
        </div>

        {/* Network Timeline Log */}
        <div className="lg:col-span-7">
          <div className="widget" style={{ minHeight: '380px' }}>
            <div className="widget-header border-b border-subtle pb-3 mb-0">
              <div className="text-sm font-bold text-main flex items-center gap-2">
                <Activity size={16} className="text-blue" /> Live Mesh Event Timeline
              </div>
            </div>

            <div className="flex-1 overflow-y-auto pr-2 h-[420px] pt-4">
              {timeline.length === 0 ? (
                <div className="flex flex-col items-center justify-center text-muted h-full opacity-50">
                  <Activity size={24} className="mb-2" />
                  <span className="text-sm font-medium">No simulation events recorded yet.</span>
                </div>
              ) : (
                <div className="space-y-3">
                  {timeline.map((event, idx) => {
                    let Icon = Activity;
                    let iconColor = 'text-blue';
                    let bgColor = 'bg-blue/10';

                    if (event.event_type === 'NODE_FAILURE' || event.event_type === 'GATEWAY_FAILURE' || event.event_type === 'node.offline') {
                      Icon = Power; iconColor = 'text-red'; bgColor = 'bg-red/10';
                    } else if (event.event_type === 'ROUTE_CHANGED' || event.event_type === 'route.changed') {
                      Icon = Route; iconColor = 'text-emerald'; bgColor = 'bg-emerald/10';
                    } else if (event.event_type === 'DEGRADE_LINK') {
                      Icon = Wifi; iconColor = 'text-amber'; bgColor = 'bg-amber/10';
                    } else if (event.event_type === 'RESTORE_NETWORK' || event.event_type === 'node.online') {
                      Icon = ShieldCheck; iconColor = 'text-emerald'; bgColor = 'bg-emerald/10';
                    }

                    return (
                      <div key={idx} className="flex gap-3 text-sm border-b border-subtle pb-3 last:border-0 last:pb-0">
                        <div className={`p-2 rounded-full shrink-0 h-8 w-8 flex items-center justify-center ${bgColor} ${iconColor}`}>
                          <Icon size={14} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="font-bold text-main">{event.event_type.replace(/_/g, ' ')}</span>
                            <span className="text-xs font-mono text-muted shrink-0">
                              {new Date(event.timestamp).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </span>
                          </div>
                          <div className="text-muted text-xs break-words">{event.message}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

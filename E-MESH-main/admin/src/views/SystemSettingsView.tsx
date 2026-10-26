import React, { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Battery,
  Cpu,
  Heart,
  Layers,
  Network,
  Power,
  Plus,
  Radio,
  RefreshCw,
  RotateCcw,
  Sliders,
  Trash2,
  Wifi,
  Zap,
  X
} from 'lucide-react';
import { api } from '../api/client';
import { SimulatedNode, SimulationNetworkStatus } from '../api/types';
import { useMeshEvent } from '../api/ws';

export const SystemSettingsView: React.FC = () => {
  const [networkStatus, setNetworkStatus] = useState<SimulationNetworkStatus | null>(null);
  const [nodes, setNodes] = useState<SimulatedNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('EM-01');
  const [loading, setLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Parameter sliders for selected node
  const [parentSelection, setParentSelection] = useState<string>('');
  const [batterySlider, setBatterySlider] = useState<number>(100);
  const [rssiSlider, setRssiSlider] = useState<number>(-60);
  const [lossSlider, setLossSlider] = useState<number>(0);
  const [latencySlider, setLatencySlider] = useState<number>(15);

  // New node drawer/form state
  const [showDrawer, setShowDrawer] = useState(false);
  const [newNodeId, setNewNodeId] = useState('');
  const [newNodeParent, setNewNodeParent] = useState('GATEWAY');
  const [newNodeBattery, setNewNodeBattery] = useState(100);

  const loadData = async () => {
    setLoading(true);
    try {
      const [status, nodesList] = await Promise.all([
        api.getSimulationNetworkStatus(),
        api.getSimulationNodes(),
      ]);
      setNetworkStatus(status);
      setNodes(nodesList);

      const target = nodesList.find((n) => n.node_id === selectedNodeId) || nodesList[0];
      if (target) {
        setSelectedNodeId(target.node_id);
        setParentSelection(target.parent_id || 'GATEWAY');
        setBatterySlider(target.battery_percent ?? 100);
        setRssiSlider(target.rssi_dbm ?? -60);
        setLossSlider(target.packet_loss_percent ?? 0);
        setLatencySlider(target.latency_ms ?? 15);
      }
    } catch (err) {
      console.error('Failed to load simulation status', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useMeshEvent('topology.updated', () => loadData());
  useMeshEvent('node.online', () => loadData());
  useMeshEvent('node.offline', () => loadData());
  useMeshEvent('node.updated', () => loadData());

  const handleNodeSelect = (nid: string) => {
    setSelectedNodeId(nid);
    const target = nodes.find((n) => n.node_id === nid);
    if (target) {
      setParentSelection(target.parent_id || 'GATEWAY');
      setBatterySlider(target.battery_percent ?? 100);
      setRssiSlider(target.rssi_dbm ?? -60);
      setLossSlider(target.packet_loss_percent ?? 0);
      setLatencySlider(target.latency_ms ?? 15);
    }
  };

  const showFeedback = (msg: string) => {
    setActionMessage(msg);
    setTimeout(() => setActionMessage(null), 3500);
  };

  const handleToggleOnline = async () => {
    const node = nodes.find((n) => n.node_id === selectedNodeId);
    if (!node) return;
    try {
      if (node.status === 'ONLINE') {
        await api.takeSimulationNodeOffline(selectedNodeId);
        showFeedback(`Node ${selectedNodeId} taken OFFLINE`);
      } else {
        await api.bringSimulationNodeOnline(selectedNodeId);
        showFeedback(`Node ${selectedNodeId} brought ONLINE`);
      }
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleRestoreNode = async () => {
    try {
      await api.restoreSimulationNode(selectedNodeId);
      showFeedback(`Node ${selectedNodeId} restored to full health`);
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleTriggerHeartbeat = async () => {
    try {
      await api.simulateNodeHeartbeat(selectedNodeId);
      showFeedback(`Heartbeat received from ${selectedNodeId}`);
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleApplySliders = async () => {
    try {
      await api.updateSimulationNode(selectedNodeId, {
        parent_id: selectedNodeId === 'GATEWAY' ? null : parentSelection,
        battery_percent: batterySlider,
        rssi_dbm: rssiSlider,
        packet_loss_percent: lossSlider,
        latency_ms: latencySlider,
      });
      showFeedback(`Node ${selectedNodeId} parameters applied`);
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleCreateNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNodeId.trim()) return;
    try {
      await api.createSimulationNode({
        node_id: newNodeId.trim().toUpperCase(),
        parent_id: newNodeParent,
        battery_percent: newNodeBattery,
      });
      setShowDrawer(false);
      setNewNodeId('');
      showFeedback(`New Node ${newNodeId} deployed into mesh`);
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDeleteNode = async (nid: string) => {
    if (!confirm(`Remove simulated node ${nid} from mesh?`)) return;
    try {
      await api.deleteSimulationNode(nid);
      showFeedback(`Node ${nid} decommissioned`);
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const currentNode = nodes.find((n) => n.node_id === selectedNodeId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Cpu size={20} className="text-primary" />
            <h2 className="text-xl font-bold text-main leading-tight">Simulation Control Lab</h2>
          </div>
          <p className="text-sm text-muted mt-1">
            Application-level simulator, dynamic self-healing tree controls
          </p>
        </div>

        <div className="flex items-center gap-3">
          {actionMessage && (
            <span className="text-xs font-mono text-emerald bg-emerald/10 px-2 py-1 rounded-sm border border-emerald/20 animate-in fade-in">
              ✓ {actionMessage}
            </span>
          )}
          <button onClick={() => setShowDrawer(true)} className="btn btn-primary">
            <Plus size={14} /> Deploy Node
          </button>
          <button onClick={loadData} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* Network Overview Summary Banner */}
      {networkStatus && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2">
          <div className="metric-widget py-3" style={{ borderTop: '2px solid var(--accent-primary)' }}>
            <span className="metric-label uppercase tracking-widest text-muted">Target Protocol</span>
            <div className="text-xl font-bold font-mono text-primary mt-1">{networkStatus.protocol_target}</div>
          </div>
          <div className="metric-widget py-3" style={{ borderTop: '2px solid var(--border-strong)' }}>
            <span className="metric-label uppercase tracking-widest text-muted">Tree Depth</span>
            <div className="text-xl font-bold font-mono text-main mt-1">{networkStatus.max_tree_depth} Layers</div>
          </div>
          <div className="metric-widget py-3" style={{ borderTop: '2px solid var(--accent-emerald)' }}>
            <span className="metric-label uppercase tracking-widest text-muted">Online / Total</span>
            <div className="text-xl font-bold font-mono text-emerald mt-1">
              {networkStatus.online_nodes} / {networkStatus.total_nodes} <span className="text-sm">Nodes</span>
            </div>
          </div>
          <div className="metric-widget py-3" style={{ borderTop: '2px solid var(--border-strong)' }}>
            <span className="metric-label uppercase tracking-widest text-muted">Active Tree Links</span>
            <div className="text-xl font-bold font-mono text-main mt-1">{networkStatus.active_links} <span className="text-sm">Links</span></div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Node Selector & Quick Actions */}
        <div className="lg:col-span-4">
          <div className="widget h-full flex flex-col p-0 overflow-hidden">
            <div className="widget-header border-b border-subtle p-3 bg-surface">
              <h3 className="text-sm font-bold flex items-center gap-2 text-main">
                <Network size={16} className="text-primary" /> Select Mesh Node
              </h3>
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-1" style={{ maxHeight: '500px' }}>
              {nodes.map((node) => {
                const isSelected = node.node_id === selectedNodeId;
                const isOnline = node.status === 'ONLINE';
                const isDegraded = node.status === 'DEGRADED';
                
                return (
                  <div
                    key={node.node_id}
                    onClick={() => handleNodeSelect(node.node_id)}
                    className={`p-3 rounded-sm cursor-pointer transition-all border ${isSelected ? 'border-primary bg-primary/5' : 'border-subtle bg-surface hover:border-strong'}`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald' : isDegraded ? 'bg-amber' : 'bg-red'}`} />
                        <span className="text-sm font-bold text-main">{node.node_id}</span>
                        {node.node_id === 'GATEWAY' && (
                          <span className="badge badge-outline text-[10px]">ROOT</span>
                        )}
                      </div>
                      <span className="text-xs font-mono text-dim">
                        Layer {node.layer}
                      </span>
                    </div>

                    <div className="flex items-center justify-between mt-2 text-[11px] text-muted font-mono">
                      <span className="flex items-center gap-1">
                        <Battery size={11} className={node.battery_percent && node.battery_percent < 20 ? 'text-red' : 'text-emerald'} />
                        {node.battery_percent}%
                      </span>
                      {node.parent_id && (
                        <span>Upstream: {node.parent_id}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Selected Node Parameter Lab */}
        <div className="lg:col-span-8">
          {currentNode ? (
            <div className="widget h-full">
              <div className="widget-header border-b border-subtle pb-4 mb-4 flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-bold text-main flex items-center gap-2">
                    <Sliders size={18} className="text-primary" /> Configure Node: {currentNode.node_id}
                  </h3>
                  <div className="text-xs font-mono text-muted mt-1 flex items-center gap-2">
                    <span>Role: {currentNode.node_id === 'GATEWAY' ? 'Root Coordinator' : 'Routing Node / End Device'}</span>
                    <span>•</span>
                    <span className={currentNode.status === 'ONLINE' ? 'text-emerald font-bold' : 'text-red font-bold'}>
                      Status: {currentNode.status}
                    </span>
                  </div>
                </div>

                {currentNode.node_id !== 'GATEWAY' && (
                  <div className="flex gap-2">
                    <button
                      onClick={handleToggleOnline}
                      className={`btn btn-sm ${currentNode.status === 'ONLINE' ? 'btn-danger' : 'btn-primary'}`}
                    >
                      <Power size={13} /> {currentNode.status === 'ONLINE' ? 'Force Offline' : 'Bring Online'}
                    </button>
                    <button onClick={() => handleDeleteNode(currentNode.node_id)} className="btn-icon text-red bg-red/5 hover:bg-red/10" title="Delete Node">
                      <Trash2 size={16} />
                    </button>
                  </div>
                )}
              </div>

              {/* Lab Parameters */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-6 mb-6">
                {/* Routing / Parent */}
                {currentNode.node_id !== 'GATEWAY' && (
                  <div className="space-y-2 p-3 bg-surface-elevated border border-subtle rounded-sm">
                    <label className="flex justify-between text-xs font-bold text-main uppercase tracking-widest">
                      <span>Upstream Parent (Routing)</span>
                      <span className="text-primary font-mono">{parentSelection}</span>
                    </label>
                    <select
                      value={parentSelection}
                      onChange={(e) => setParentSelection(e.target.value)}
                      className="form-select font-mono text-sm"
                    >
                      {nodes
                        .filter((n) => n.node_id !== currentNode.node_id)
                        .map((n) => (
                          <option key={n.node_id} value={n.node_id}>
                            {n.node_id} (Layer {n.layer})
                          </option>
                        ))}
                    </select>
                    <p className="text-[11px] text-dim">
                      Force an upstream route change in the mesh topology.
                    </p>
                  </div>
                )}

                {/* Battery Override */}
                <div className="space-y-2 p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <label className="flex justify-between text-xs font-bold text-main uppercase tracking-widest">
                    <span>Battery Capacity</span>
                    <span className={`font-mono font-bold ${batterySlider < 20 ? 'text-red' : 'text-emerald'}`}>{batterySlider}%</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={batterySlider}
                    onChange={(e) => setBatterySlider(parseInt(e.target.value, 10))}
                    className="w-full h-1.5 bg-surface rounded-full appearance-none outline-none focus:outline-none"
                    style={{ 
                      background: `linear-gradient(to right, var(--accent-${batterySlider < 20 ? 'red' : 'emerald'}) ${batterySlider}%, var(--bg-surface) ${batterySlider}%)` 
                    }}
                  />
                  <div className="flex justify-between text-[10px] text-muted font-mono">
                    <span>Dead (0%)</span>
                    <span>Full (100%)</span>
                  </div>
                </div>

                {/* Signal Strength (RSSI) */}
                <div className="space-y-2 p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <label className="flex justify-between text-xs font-bold text-main uppercase tracking-widest">
                    <span>Link Signal (RSSI)</span>
                    <span className="text-blue font-mono font-bold">{rssiSlider} dBm</span>
                  </label>
                  <input
                    type="range"
                    min="-100"
                    max="-30"
                    step="1"
                    value={rssiSlider}
                    onChange={(e) => setRssiSlider(parseInt(e.target.value, 10))}
                    className="w-full h-1.5 bg-surface rounded-full appearance-none outline-none focus:outline-none"
                    style={{ 
                      background: `linear-gradient(to right, var(--accent-blue) ${((rssiSlider + 100) / 70) * 100}%, var(--bg-surface) ${((rssiSlider + 100) / 70) * 100}%)` 
                    }}
                  />
                  <div className="flex justify-between text-[10px] text-muted font-mono">
                    <span>Weak (-100)</span>
                    <span>Excellent (-30)</span>
                  </div>
                </div>

                {/* Packet Loss */}
                <div className="space-y-2 p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <label className="flex justify-between text-xs font-bold text-main uppercase tracking-widest">
                    <span>Link Packet Loss</span>
                    <span className={`font-mono font-bold ${lossSlider > 10 ? 'text-amber' : 'text-emerald'}`}>{lossSlider}%</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={lossSlider}
                    onChange={(e) => setLossSlider(parseInt(e.target.value, 10))}
                    className="w-full h-1.5 bg-surface rounded-full appearance-none outline-none focus:outline-none"
                    style={{ 
                      background: `linear-gradient(to right, var(--accent-${lossSlider > 10 ? 'amber' : 'emerald'}) ${lossSlider}%, var(--bg-surface) ${lossSlider}%)` 
                    }}
                  />
                  <div className="flex justify-between text-[10px] text-muted font-mono">
                    <span>Perfect (0%)</span>
                    <span>Total Drop (100%)</span>
                  </div>
                </div>

                {/* Latency */}
                <div className="space-y-2 p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <label className="flex justify-between text-xs font-bold text-main uppercase tracking-widest">
                    <span>Processing Latency</span>
                    <span className={`font-mono font-bold ${latencySlider > 100 ? 'text-amber' : 'text-main'}`}>{latencySlider} ms</span>
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="500"
                    step="5"
                    value={latencySlider}
                    onChange={(e) => setLatencySlider(parseInt(e.target.value, 10))}
                    className="w-full h-1.5 bg-surface rounded-full appearance-none outline-none focus:outline-none"
                    style={{ 
                      background: `linear-gradient(to right, var(--border-strong) ${((latencySlider - 5) / 495) * 100}%, var(--bg-surface) ${((latencySlider - 5) / 495) * 100}%)` 
                    }}
                  />
                  <div className="flex justify-between text-[10px] text-muted font-mono">
                    <span>Fast (5ms)</span>
                    <span>Congested (500ms)</span>
                  </div>
                </div>
              </div>

              <div className="mt-auto pt-4 flex flex-wrap gap-3 border-t border-subtle">
                <button onClick={handleApplySliders} className="btn btn-primary">
                  <Sliders size={14} /> Apply Node Parameters
                </button>
                <button onClick={handleRestoreNode} className="btn bg-emerald/10 text-emerald hover:bg-emerald/20 border-emerald/20">
                  <Heart size={14} /> Restore Health
                </button>
                <button onClick={handleTriggerHeartbeat} className="btn border-subtle text-main bg-surface hover:bg-surface-elevated">
                  <Wifi size={14} className="text-primary" /> Force Ping
                </button>
              </div>
            </div>
          ) : (
            <div className="widget h-full flex flex-col items-center justify-center p-12 text-center border-dashed">
              <Cpu size={48} className="text-dim mb-4 opacity-50" />
              <h3 className="text-lg font-bold text-main">No Node Selected</h3>
              <p className="text-sm text-muted mt-1 max-w-sm">
                Select a mesh node from the list to view and edit its simulation parameters and routing topology.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Deploy Node Drawer */}
      {showDrawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowDrawer(false)}></div>
          <div className="drawer-panel">
            <div className="drawer-header">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Plus size={16} className="text-primary" /> Deploy Simulated Node
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content space-y-4">
              <div className="bg-surface-elevated p-3 border border-subtle rounded-sm text-sm text-muted mb-4">
                Deploying a new node will force a network re-convergence as routing paths are discovered.
              </div>

              <form id="node-form" onSubmit={handleCreateNode} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Node Identifier (Unique)</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. EM-10"
                    className="form-input font-mono"
                    value={newNodeId}
                    onChange={(e) => setNewNodeId(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Initial Parent Route</label>
                  <select
                    required
                    className="form-select font-mono text-sm"
                    value={newNodeParent}
                    onChange={(e) => setNewNodeParent(e.target.value)}
                  >
                    {nodes.map((n) => (
                      <option key={n.node_id} value={n.node_id}>
                        {n.node_id} (Layer {n.layer})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Starting Battery (%)</label>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    required
                    className="form-input font-mono"
                    value={newNodeBattery}
                    onChange={(e) => setNewNodeBattery(parseInt(e.target.value, 10))}
                  />
                </div>
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">Cancel</button>
              <button type="submit" form="node-form" className="btn btn-primary">
                Deploy to Mesh
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

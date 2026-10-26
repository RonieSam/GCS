import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Battery,
  Cpu,
  Edit2,
  Plus,
  RefreshCw,
  Signal,
  Trash2,
  X,
  Search,
  MoreVertical,
  Activity,
  AlertTriangle,
} from 'lucide-react';
import { api } from '../api/client';
import { MeshNode } from '../api/types';

export const NodesView: React.FC = () => {
  const [nodes, setNodes] = useState<MeshNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [showDrawer, setShowDrawer] = useState(false);
  const [editNode, setEditNode] = useState<MeshNode | null>(null);

  // Form states
  const [nodeId, setNodeId] = useState('');
  const [nodeName, setNodeName] = useState('');
  const [batteryLevel, setBatteryLevel] = useState(100);
  const [signalQuality, setSignalQuality] = useState(90);
  const [hopCount, setHopCount] = useState(1);
  const [status, setStatus] = useState('ONLINE');
  const [actionLoading, setActionLoading] = useState(false);

  const [clearLoading, setClearLoading] = useState(false);
  const [filter, setFilter] = useState('');

  const loadNodes = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const resp = await api.getNodes({ page_size: 100 });
      setNodes(resp.data);
    } catch (err) {
      console.error('Failed to load nodes', err);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  /* Initial load */
  useEffect(() => { loadNodes(); }, [loadNodes]);

  /* Auto-refresh every second (silent — no spinner) */
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    intervalRef.current = setInterval(() => loadNodes(true), 1000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [loadNodes]);

  const resetForm = () => {
    setEditNode(null);
    setNodeId('');
    setNodeName('');
    setBatteryLevel(100);
    setSignalQuality(90);
    setHopCount(1);
    setStatus('ONLINE');
  };

  const handleCreateNode = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createNode({
        node_id: nodeId,
        name: nodeName,
        battery_level: batteryLevel,
        signal_quality: signalQuality,
        hop_count: hopCount,
      });
      setShowDrawer(false);
      resetForm();
      await loadNodes();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editNode) return;
    setActionLoading(true);
    try {
      await api.updateNode(editNode.id, {
        name: nodeName,
        status,
        battery_level: batteryLevel,
        signal_quality: signalQuality,
        hop_count: hopCount,
      });
      setShowDrawer(false);
      resetForm();
      await loadNodes();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteNode = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to decommission node "${name}"?`)) return;
    try {
      await api.deleteNode(id);
      setNodes(prev => prev.filter(n => n.id !== id));
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleClearAll = async () => {
    if (nodes.length === 0) return;
    if (!confirm(`This will permanently remove ALL ${nodes.length} registered node(s). Are you sure?`)) return;
    setClearLoading(true);
    try {
      await Promise.all(nodes.map(n => api.deleteNode(n.id)));
      setNodes([]);
    } catch (err: any) {
      alert('Some nodes could not be deleted: ' + err.message);
      await loadNodes();
    } finally {
      setClearLoading(false);
    }
  };

  const openAdd = () => {
    resetForm();
    setShowDrawer(true);
  };

  const openEdit = (n: MeshNode) => {
    setEditNode(n);
    setNodeId(n.node_id);
    setNodeName(n.name);
    setStatus(n.status);
    setBatteryLevel(n.battery_percent ?? 100);
    setSignalQuality(n.rssi_dbm ?? 0);
    setHopCount(n.hop_count);
    setShowDrawer(true);
  };

  return (
    <div className="space-y-4">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Infrastructure Devices</h2>
          <p className="text-sm text-muted mt-1">
            Registered wireless relay nodes ({nodes.length})
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input
              type="text"
              placeholder="Filter devices..."
              className="form-input pl-8"
              style={{ width: '200px' }}
              value={filter}
              onChange={e => setFilter(e.target.value)}
            />
          </div>
          <button onClick={() => loadNodes()} disabled={loading} className="btn" title="Refresh now">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          {nodes.length > 0 && (
            <button
              onClick={handleClearAll}
              disabled={clearLoading}
              className="btn hover:text-red hover:border-red/40"
              title="Remove all nodes"
            >
              <AlertTriangle size={14} />
              {clearLoading ? 'Clearing...' : 'Clear All'}
            </button>
          )}
          <button onClick={openAdd} className="btn btn-primary">
            <Plus size={14} /> Register Node
          </button>
        </div>
      </div>

      {/* Nodes Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Node ID</th>
              <th>Name</th>
              <th>Health / Batt</th>
              <th>Signal</th>
              <th>Route</th>
              <th>Firmware</th>
              <th>Last Seen</th>
              <th className="actions"></th>
            </tr>
          </thead>
          <tbody>
            {nodes.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center p-8 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <Activity size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No mesh nodes registered.</span>
                  </div>
                </td>
              </tr>
            ) : (
              nodes
                .filter(n =>
                  !filter ||
                  n.node_id.toLowerCase().includes(filter.toLowerCase()) ||
                  (n.name || '').toLowerCase().includes(filter.toLowerCase())
                )
                .map((node) => {
                const isOnline = node.status === 'ONLINE';
                const isDegraded = node.status === 'DEGRADED';
                const statusColor = isOnline ? 'emerald' : isDegraded ? 'amber' : 'red';

                return (
                  <tr key={node.id} className="hover:bg-surface-elevated cursor-pointer" onClick={() => openEdit(node)}>
                    <td>
                      <div className="status-indicator">
                        <span className={`status-dot bg-${statusColor} ${isOnline ? 'animate-pulse' : ''}`}></span>
                        <span className="text-xs uppercase">{node.status}</span>
                      </div>
                    </td>
                    <td className="font-mono text-xs font-bold text-blue">{node.node_id}</td>
                    <td className="font-semibold text-main">{node.name}</td>
                    <td>
                      <div className="flex items-center gap-1 font-mono text-xs text-emerald">
                        <Battery size={12} /> {node.battery_percent ?? 0}%
                      </div>
                    </td>
                    <td>
                      <div className="flex items-center gap-1 font-mono text-xs text-blue">
                        <Signal size={12} /> {node.rssi_dbm ?? 0} dBm
                      </div>
                    </td>
                    <td className="font-mono text-xs text-muted">{node.hop_count} Hop{node.hop_count === 1 ? '' : 's'}</td>
                    <td className="font-mono text-xs text-dim">{node.firmware_version || 'v1.4.0'}</td>
                    <td className="font-mono text-xs text-muted">
                      {node.last_heartbeat ? new Date(node.last_heartbeat).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Live'}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => handleDeleteNode(node.id, node.name)} className="btn-icon hover:text-red hover:bg-red/5" title="Remove Node">
                          <Trash2 size={14} />
                        </button>
                        <button onClick={() => openEdit(node)} className="btn-icon" title="Node Options">
                          <MoreVertical size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Side Drawer for Add/Edit */}
      {showDrawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowDrawer(false)}></div>
          <div className="drawer-panel">
            <div className="drawer-header">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Cpu size={16} className="text-primary" />
                {editNode ? 'Device Configuration' : 'Register New Device'}
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content space-y-4">
              {editNode && (
                <div className="widget bg-surface-elevated border-subtle mb-4">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center bg-card border border-subtle rounded-md" style={{ width: '40px', height: '40px' }}>
                      <Cpu size={20} className="text-blue" />
                    </div>
                    <div>
                      <div className="text-sm font-bold">{editNode.name}</div>
                      <div className="text-xs font-mono text-muted">{editNode.node_id}</div>
                    </div>
                  </div>
                </div>
              )}

              <form id="node-form" onSubmit={editNode ? handleUpdateNode : handleCreateNode} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Hardware Identifier</label>
                  <input
                    type="text"
                    required
                    placeholder="MAC or Unique ID"
                    className="form-input font-mono"
                    value={nodeId}
                    onChange={(e) => setNodeId(e.target.value)}
                    disabled={!!editNode}
                  />
                  {!editNode && <span className="text-xs text-dim">Must match the exact MAC or flashed ID of the physical ESP32.</span>}
                </div>

                <div className="form-group">
                  <label className="form-label">Display Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Sector 4 Relay"
                    className="form-input"
                    value={nodeName}
                    onChange={(e) => setNodeName(e.target.value)}
                  />
                </div>

                {editNode && (
                  <div className="form-group">
                    <label className="form-label">Operational Status</label>
                    <select className="form-select" value={status} onChange={(e) => setStatus(e.target.value)}>
                      <option value="ONLINE">Online (Active)</option>
                      <option value="DEGRADED">Degraded (Warning)</option>
                      <option value="OFFLINE">Offline (Critical)</option>
                    </select>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  <div className="form-group">
                    <label className="form-label">Simulated Battery (%)</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      className="form-input"
                      value={batteryLevel}
                      onChange={(e) => setBatteryLevel(parseInt(e.target.value))}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Simulated Signal (%)</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      className="form-input"
                      value={signalQuality}
                      onChange={(e) => setSignalQuality(parseInt(e.target.value))}
                    />
                  </div>
                </div>
                
                <div className="form-group">
                  <label className="form-label">Tree Hop Count</label>
                  <input
                    type="number"
                    min="1"
                    className="form-input"
                    value={hopCount}
                    onChange={(e) => setHopCount(parseInt(e.target.value))}
                  />
                </div>
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">
                Cancel
              </button>
              <button type="submit" form="node-form" disabled={actionLoading} className="btn btn-primary">
                {actionLoading ? 'Saving...' : (editNode ? 'Save Configuration' : 'Register Device')}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

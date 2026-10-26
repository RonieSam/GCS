import React, { useEffect, useState } from 'react';
import {
  Activity,
  Battery,
  ChevronRight,
  Cpu,
  Info,
  Layers,
  Network,
  MapPin,
  Radio,
  RefreshCw,
  Route,
  Signal,
  Wifi,
  Zap,
} from 'lucide-react';
import { api } from '../api/client';
import { MeshNodeLink, MeshNode, TopologyData } from '../api/types';
import { useMeshEvent } from '../api/ws';
import { NodeTelemetryChart } from '../components/NodeTelemetryChart';

export const TopologyView: React.FC = () => {
  const [topology, setTopology] = useState<{ nodes: MeshNode[]; links: MeshNodeLink[]; max_depth: number; root_id: string }>({
    root_id: 'GATEWAY',
    nodes: [],
    links: [],
    max_depth: 1,
  });
  const [selectedNode, setSelectedNode] = useState<MeshNode | null>(null);
  const [selectedLink, setSelectedLink] = useState<MeshNodeLink | null>(null);
  const [selectedRouteNodeId, setSelectedRouteNodeId] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    setLoading(true);
    try {
      const data = await api.getTopology();
      const max_depth = data.nodes.length > 0 ? Math.max(...data.nodes.map(n => n.hop_count || 1)) : 1;
      const rootNode = data.nodes.find(n => n.hop_count === 1) || data.nodes[0];
      const root_id = rootNode ? rootNode.node_id : 'GATEWAY';
      
      setTopology({
        nodes: data.nodes,
        links: data.links,
        max_depth,
        root_id
      });
      if (data.nodes.length > 0) {
        if (selectedNode) {
          const updated = data.nodes.find((n) => n.node_id === selectedNode.node_id);
          if (updated) setSelectedNode(updated);
        } else {
          setSelectedNode(data.nodes[0]);
        }
      }
    } catch (err) {
      console.error('Failed to load topology', err);
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
  useMeshEvent('route.changed', () => loadData());

  // ── Hierarchical Tree Layout Positioning ──────────────────────────────────
  const width = 800;
  const height = 520;
  const nodePositions = new Map<string, { x: number; y: number }>();

  const layersMap: Record<number, MeshNode[]> = {};
  topology.nodes.forEach((node) => {
    const layer = node.hop_count || 1;
    if (!layersMap[layer]) layersMap[layer] = [];
    layersMap[layer].push(node);
  });

  const totalLayers = Math.max(1, topology.max_depth || 1);
  const layerHeight = totalLayers > 1 ? (height - 140) / (totalLayers - 1) : 0;

  Object.entries(layersMap).forEach(([layerStr, layerNodes]) => {
    const layerNum = parseInt(layerStr, 10);
    const y = 80 + (layerNum - 1) * layerHeight;
    const count = layerNodes.length;

    layerNodes.forEach((node, idx) => {
      const step = width / (count + 1);
      const x = (idx + 1) * step;
      nodePositions.set(node.node_id, { x, y });
    });
  });

  const targetRouteNode = topology.nodes.find((n) => n.node_id === selectedRouteNodeId);
  const activeRoutePath = targetRouteNode?.current_route ? targetRouteNode.current_route.split(',') : [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Network size={20} className="text-primary" />
            <h2 className="text-xl font-bold text-main leading-tight">Mesh Topology</h2>
          </div>
          <p className="text-sm text-muted mt-1">
            Real-time tree matrix and self-healing route paths
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-surface-elevated border border-subtle text-xs font-mono">
            <Layers size={14} className="text-primary" />
            <span className="text-muted">Tree Depth: <strong className="text-main">{topology.max_depth} Layers</strong></span>
          </div>

          <button onClick={loadData} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh Map
          </button>
        </div>
      </div>

      {/* Route Path Tracer */}
      <div className="widget" style={{ borderLeft: '3px solid var(--accent-emerald)', background: 'rgba(136, 179, 148, 0.04)' }}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-sm bg-emerald/10 text-emerald">
              <Route size={16} />
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-widest text-muted font-mono">
                Active Multi-Hop Route
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className="badge badge-outline">Client App</span>
                <ChevronRight size={14} className="text-muted" />
                {activeRoutePath.length > 0 ? (
                  activeRoutePath.map((nid, i) => (
                    <React.Fragment key={nid}>
                      <span className={`badge ${nid === 'GATEWAY' ? 'bg-primary text-white' : 'badge-outline'}`}>
                        {nid}
                      </span>
                      {i < activeRoutePath.length - 1 && <ChevronRight size={14} className="text-muted" />}
                    </React.Fragment>
                  ))
                ) : (
                  <span className="text-xs font-mono text-muted">No route calculated</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-muted">Trace Origin:</span>
            <select
              value={selectedRouteNodeId}
              onChange={(e) => setSelectedRouteNodeId(e.target.value)}
              className="form-select text-xs py-1 px-2"
              style={{ width: '140px' }}
            >
              {topology.nodes.map((n) => (
                <option key={n.node_id} value={n.node_id}>
                  {n.node_id} (Layer {n.hop_count || 1})
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* SVG Mesh Canvas */}
        <div className="lg:col-span-8">
          <div className="widget h-full p-0 overflow-hidden relative" style={{ minHeight: '560px' }}>
            <div className="absolute inset-0 opacity-40 pointer-events-none" style={{
              backgroundImage: 'radial-gradient(var(--border-subtle) 1px, transparent 1px)',
              backgroundSize: '24px 24px'
            }} />
            
            <div className="absolute left-4 top-4 flex flex-col gap-24 pointer-events-none opacity-50 font-mono text-xs text-muted font-bold">
              <div>LAYER 1 • ROOT GATEWAY</div>
              <div>LAYER 2 • RELAYS</div>
              <div>LAYER 3 • LEAF NODES</div>
            </div>

            <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full relative z-10" style={{ minHeight: '560px' }}>
              <defs>
              </defs>

              {/* Render Links */}
              {topology.links.map((link) => {
                const srcPos = nodePositions.get(link.source_node_id);
                const tgtPos = nodePositions.get(link.target_node_id);
                if (!srcPos || !tgtPos) return null;

                const isRouteHighlighted =
                  activeRoutePath.includes(link.source_node_id) &&
                  activeRoutePath.includes(link.target_node_id);

                const isDown = link.status === 'DOWN';
                const isDegraded = link.status === 'DEGRADED';

                let strokeColor = 'var(--border-strong)';
                if (isRouteHighlighted) strokeColor = 'var(--accent-emerald)';
                else if (isDown) strokeColor = 'var(--accent-red)';
                else if (isDegraded) strokeColor = 'var(--accent-amber)';

                return (
                  <g key={`${link.source_node_id}-${link.target_node_id}`}>
                    <line
                      x1={srcPos.x}
                      y1={srcPos.y}
                      x2={tgtPos.x}
                      y2={tgtPos.y}
                      stroke={strokeColor}
                      strokeWidth={isRouteHighlighted ? 3 : 2}
                      strokeDasharray={isDown ? '4,4' : isDegraded ? '6,3' : 'none'}
                      strokeOpacity={isDown ? 0.4 : 0.8}
                      className="transition-all cursor-pointer hover:opacity-100"
                      onClick={() => {
                        setSelectedLink(link);
                        setSelectedNode(null);
                      }}
                    />
                    <text
                      x={(srcPos.x + tgtPos.x) / 2}
                      y={(srcPos.y + tgtPos.y) / 2 - 6}
                      fill={isRouteHighlighted ? 'var(--accent-emerald)' : 'var(--text-dim)'}
                      fontSize="10"
                      fontFamily="var(--font-mono)"
                      textAnchor="middle"
                      className="pointer-events-none"
                    >
                      {link.rssi_dbm} dBm
                    </text>
                  </g>
                );
              })}

              {/* Render Nodes */}
              {topology.nodes.map((node) => {
                const pos = nodePositions.get(node.node_id);
                if (!pos) return null;

                const isRoot = node.node_id === topology.root_id;
                const isSelected = selectedNode?.node_id === node.node_id;
                const inRoute = activeRoutePath.includes(node.node_id);

                let fillColor = 'var(--bg-surface)';
                let strokeColor = 'var(--border-strong)';
                if (isRoot) strokeColor = 'var(--accent-primary)';
                if (inRoute) strokeColor = 'var(--accent-emerald)';

                if (node.status === 'DEGRADED') strokeColor = 'var(--accent-amber)';
                if (node.status === 'OFFLINE') strokeColor = 'var(--accent-red)';

                return (
                  <g
                    key={node.node_id}
                    transform={`translate(${pos.x},${pos.y})`}
                    className="cursor-pointer transition-transform hover:scale-110"
                    onClick={() => {
                      setSelectedNode(node);
                      setSelectedLink(null);
                    }}
                  >
                    <circle
                      r={isSelected ? 22 : 18}
                      fill={fillColor}
                      stroke={strokeColor}
                      strokeWidth={isSelected ? 4 : 2}
                      className="transition-all"
                    />
                    {isRoot && (
                      <circle r={28} fill="none" stroke="var(--accent-primary)" strokeWidth="1" strokeDasharray="4,4" className="animate-spin" style={{ animationDuration: '10s' }} />
                    )}
                    <text
                      y={4}
                      fill={strokeColor}
                      fontSize={16}
                      fontFamily="var(--font-sans)"
                      textAnchor="middle"
                      dominantBaseline="middle"
                      className="font-bold pointer-events-none"
                    >
                      {isRoot ? 'G' : 'N'}
                    </text>
                    <rect x="-24" y="24" width="48" height="18" rx="4" fill="var(--bg-card)" stroke="var(--border-subtle)" strokeWidth="1" />
                    <text
                      y={36}
                      fill="var(--text-main)"
                      fontSize="9"
                      fontFamily="var(--font-mono)"
                      textAnchor="middle"
                      className="font-bold pointer-events-none"
                    >
                      {node.node_id}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        {/* Right Detail Panel */}
        <div className="lg:col-span-4 flex flex-col space-y-4">
          <div className="widget flex-1">
            {selectedNode && (
              <div className="animate-in fade-in h-full flex flex-col">
                <div className="widget-header border-b border-subtle pb-3 mb-4">
                  <div className="flex items-center gap-2">
                    <Cpu size={16} className="text-primary" />
                    <span className="font-bold text-lg leading-none">Node Inspector</span>
                  </div>
                </div>

                <div className="flex items-center justify-between mb-6 bg-surface-elevated p-3 border border-subtle rounded-sm">
                  <div>
                    <div className="text-xs text-muted uppercase tracking-widest font-bold mb-1">Hardware ID</div>
                    <div className="text-lg font-mono text-main font-bold">{selectedNode.node_id}</div>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <span className={`badge ${selectedNode.status === 'ONLINE' ? 'bg-emerald text-white' : 'bg-red text-white'}`}>
                      {selectedNode.status}
                    </span>
                    {selectedNode.has_gps && (
                      <span className="badge bg-blue text-white text-[10px] uppercase">
                        GPS Connected
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Layers size={14}/> <span className="text-xs font-semibold">Tree Layer</span></div>
                    <div className="text-xl font-mono text-main">{selectedNode.hop_count || 1}</div>
                  </div>
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Route size={14}/> <span className="text-xs font-semibold">Hop Count</span></div>
                    <div className="text-xl font-mono text-main">{selectedNode.hop_count || 1}</div>
                  </div>
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Battery size={14}/> <span className="text-xs font-semibold">Battery</span></div>
                    <div className="text-xl font-mono text-main">{selectedNode.battery_percent ?? 'N/A'}%</div>
                  </div>
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Activity size={14}/> <span className="text-xs font-semibold">Last Heartbeat</span></div>
                    <div className="text-xs font-mono text-main truncate" title={selectedNode.last_heartbeat ?? ''}>{selectedNode.last_heartbeat ? new Date(selectedNode.last_heartbeat).toLocaleTimeString() : 'N/A'}</div>
                  </div>
                </div>

                {/* GPS Data */}
                {selectedNode.has_gps && (
                  <div className="mb-4">
                    <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2 flex items-center gap-1">
                      <MapPin size={12} className="text-emerald" /> GPS (M8N)
                    </div>
                    {selectedNode.gps_lat != null ? (
                      <div className="grid grid-cols-2 gap-2">
                        <div className="p-2 border border-subtle rounded-sm bg-surface-elevated col-span-2">
                          <div className="text-xs text-muted mb-1">Coordinates</div>
                          <div className="text-sm font-mono text-emerald font-bold">
                            {selectedNode.gps_lat.toFixed(6)}°, {selectedNode.gps_lon?.toFixed(6)}°
                          </div>
                        </div>
                        <div className="p-2 border border-subtle rounded-sm bg-surface-elevated">
                          <div className="text-xs text-muted mb-1">Altitude</div>
                          <div className="text-sm font-mono text-main">
                            {selectedNode.gps_alt_m != null ? `${selectedNode.gps_alt_m.toFixed(1)} m` : 'N/A'}
                          </div>
                        </div>
                        <div className="p-2 border border-subtle rounded-sm bg-surface-elevated">
                          <div className="text-xs text-muted mb-1">Satellites</div>
                          <div className="text-sm font-mono text-main">
                            {selectedNode.gps_sats ?? 'N/A'}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-muted italic p-2 border border-subtle rounded-sm bg-surface-elevated">
                        GPS connected — waiting for satellite fix…
                      </div>
                    )}
                  </div>
                )}

                {/* BMP280 Environmental Data */}
                {(selectedNode.temperature_c != null || selectedNode.pressure_hpa != null) && (
                  <div className="mb-4">
                    <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2 flex items-center gap-1">
                      <Zap size={12} className="text-amber" /> Environment (BMP280)
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="p-2 border border-subtle rounded-sm bg-surface-elevated">
                        <div className="text-xs text-muted mb-1">Temperature</div>
                        <div className="text-base font-mono text-amber font-bold">
                          {selectedNode.temperature_c != null ? `${selectedNode.temperature_c.toFixed(1)} °C` : 'N/A'}
                        </div>
                      </div>
                      <div className="p-2 border border-subtle rounded-sm bg-surface-elevated">
                        <div className="text-xs text-muted mb-1">Pressure</div>
                        <div className="text-base font-mono text-blue font-bold">
                          {selectedNode.pressure_hpa != null ? `${selectedNode.pressure_hpa.toFixed(1)} hPa` : 'N/A'}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* MPU6050 IMU Data */}
                {(selectedNode.accel_x != null) && (
                  <div className="mb-4">
                    <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2 flex items-center gap-1">
                      <Radio size={12} className="text-primary" /> IMU (MPU6050) — Raw
                    </div>
                    <div className="grid grid-cols-3 gap-1 mb-1">
                      {[['Ax', selectedNode.accel_x], ['Ay', selectedNode.accel_y], ['Az', selectedNode.accel_z]].map(([label, val]) => (
                        <div key={String(label)} className="p-1.5 border border-subtle rounded-sm bg-surface-elevated text-center">
                          <div className="text-xs text-muted">{label}</div>
                          <div className="text-xs font-mono text-primary">{val}</div>
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-3 gap-1">
                      {[['Gx', selectedNode.gyro_x], ['Gy', selectedNode.gyro_y], ['Gz', selectedNode.gyro_z]].map(([label, val]) => (
                        <div key={String(label)} className="p-1.5 border border-subtle rounded-sm bg-surface-elevated text-center">
                          <div className="text-xs text-muted">{label}</div>
                          <div className="text-xs font-mono text-emerald">{val}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Historical Telemetry Charts */}
                <NodeTelemetryChart nodeId={selectedNode.id} />

                <div className="mt-auto pt-3 border-t border-subtle">
                  <div className="text-xs font-bold uppercase tracking-widest text-muted mb-2">Active Routing Path</div>
                  <div className="flex flex-wrap gap-1 p-2 bg-surface-elevated border border-subtle rounded-sm">
                    {selectedNode.current_route ? selectedNode.current_route.split(',').map((n, i, arr) => (
                      <React.Fragment key={i}>
                        <span className="font-mono text-xs">{n}</span>
                        {i < arr.length - 1 && <ChevronRight size={12} className="text-dim" />}
                      </React.Fragment>
                    )) : <span className="font-mono text-xs text-muted">No route</span>}
                  </div>
                </div>
              </div>
            )}

            {selectedLink && !selectedNode && (
               <div className="animate-in fade-in h-full flex flex-col">
                <div className="widget-header border-b border-subtle pb-3 mb-4">
                  <div className="flex items-center gap-2">
                    <Wifi size={16} className="text-blue" />
                    <span className="font-bold text-lg leading-none">Link Inspector</span>
                  </div>
                </div>

                <div className="flex items-center justify-between mb-6 bg-surface-elevated p-3 border border-subtle rounded-sm">
                  <div className="flex items-center gap-2 font-mono text-sm font-bold">
                    <span className="text-main">{selectedLink.source_node_id}</span>
                    <Radio size={14} className="text-muted" />
                    <span className="text-main">{selectedLink.target_node_id}</span>
                  </div>
                  <span className={`badge ${selectedLink.status === 'ACTIVE' ? 'badge-outline text-emerald' : 'badge-outline text-red'}`}>
                    {selectedLink.status}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 mb-6">
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Signal size={14}/> <span className="text-xs font-semibold">Signal (RSSI)</span></div>
                    <div className="text-xl font-mono text-main">{selectedLink.rssi_dbm ?? 'N/A'} <span className="text-xs">dBm</span></div>
                  </div>
                  <div className="p-3 border border-subtle rounded-sm bg-surface">
                    <div className="flex items-center gap-2 text-muted mb-2"><Zap size={14}/> <span className="text-xs font-semibold">Link Quality</span></div>
                    <div className="text-xl font-mono text-main">{selectedLink.link_quality ?? 100} <span className="text-xs">%</span></div>
                  </div>
                </div>
               </div>
            )}

            {!selectedNode && !selectedLink && (
              <div className="h-full flex flex-col items-center justify-center p-8 text-center text-muted gap-3">
                <Info size={32} className="opacity-20" />
                <div>
                  <div className="font-bold text-sm text-main">Interactive Map</div>
                  <div className="text-xs mt-1">Select any node or link segment on the topology map to inspect its real-time telemetry.</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

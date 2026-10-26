import React, { useCallback, useEffect, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Activity,
  Clock,
  Filter,
  MapPin,
  RefreshCw,
  Shield,
  Users,
  Wifi,
} from 'lucide-react';
import { api } from '../api/client';
import { HeatmapResponse, LocationPoint, LocationUser } from '../api/types';
import { useMeshEvent } from '../api/ws';

const ROLE_COLORS: Record<string, string> = {
  CIVILIAN: '#3b82f6',
  RESPONDER: '#10b981',
  INCIDENT_MANAGER: '#f59e0b',
  ADMIN: '#ef4444',
  VIEWER: '#94a3b8',
};

const ROLE_BADGE: Record<string, string> = {
  CIVILIAN: 'badge-blue',
  RESPONDER: 'badge-emerald',
  INCIDENT_MANAGER: 'badge-amber',
  ADMIN: 'badge-red',
  VIEWER: 'badge-gray',
};

const TIME_WINDOWS = [
  { label: '5 min', value: 5 },
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '1 hour', value: 60 },
  { label: '4 hours', value: 240 },
];

// Helper component to auto-fit the map bounds to the data
const MapBoundsFitter: React.FC<{ bounds: HeatmapResponse['bounds'] }> = ({ bounds }) => {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds([
        [bounds.min_lat, bounds.min_lng],
        [bounds.max_lat, bounds.max_lng]
      ], { padding: [50, 50], maxZoom: 18 });
    }
  }, [bounds, map]);
  return null;
};

export const HeatmapView: React.FC = () => {
  const [heatmap, setHeatmap] = useState<HeatmapResponse | null>(null);
  const [users, setUsers] = useState<LocationUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [windowMinutes, setWindowMinutes] = useState(30);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  
  // Default center if no data
  const defaultCenter: [number, number] = [0, 0];
  const defaultZoom = 2;

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [hmData, usersData] = await Promise.all([
        api.getHeatmapData(windowMinutes),
        api.getLocationUsers(windowMinutes),
      ]);
      setHeatmap(hmData);
      setUsers(usersData);
      setLastRefresh(new Date());
    } catch (err) {
      console.error('Heatmap load error:', err);
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    const timer = setInterval(loadData, 15000);
    return () => clearInterval(timer);
  }, [loadData]);

  useMeshEvent('user.location_updated', () => {
    loadData();
  });

  const roleCounts = users.reduce<Record<string, number>>((acc, u) => {
    acc[u.role] = (acc[u.role] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight flex items-center gap-2">
            <MapPin size={20} className="text-red" />
            Civilian Density Heatmap (Satellite)
          </h2>
          <p className="text-sm text-muted mt-1">
            Real-time GPS positions on Esri World Imagery — {heatmap?.total_active ?? 0} active in the last {windowMinutes} min
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-muted font-mono">
            <Clock size={12} />
            {lastRefresh.toLocaleTimeString()}
          </div>
          <button onClick={loadData} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* KPI Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card p-4 flex items-center gap-3">
          <div className="p-2" style={{ background: 'rgba(59,130,246,0.12)', borderRadius: 8 }}>
            <Users size={18} className="text-blue" />
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-main">{heatmap?.total_active ?? 0}</div>
            <div className="text-xs text-muted">Active Users</div>
          </div>
        </div>
        {Object.entries(roleCounts).map(([role, count]) => (
          <div key={role} className="card p-4 flex items-center gap-3">
            <div className="p-2" style={{ background: 'rgba(59,130,246,0.08)', borderRadius: 8 }}>
              <Shield size={18} className="text-muted" />
            </div>
            <div>
              <div className="text-2xl font-bold font-mono text-main">{count}</div>
              <div className="text-xs text-muted capitalize">{role.replace(/_/g, ' ')}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Filter bar */}
      <div className="widget bg-surface-elevated border-subtle p-3 flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-muted" />
          <span className="text-xs text-muted font-semibold">Time Window:</span>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {TIME_WINDOWS.map(tw => (
            <button
              key={tw.value}
              onClick={() => setWindowMinutes(tw.value)}
              className={`btn btn-sm ${windowMinutes === tw.value ? 'btn-primary' : ''}`}
            >
              {tw.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto text-xs text-muted">
          <Wifi size={12} className="text-emerald animate-pulse" />
          Auto-refreshes every 15s
        </div>
      </div>

      {/* Leaflet Satellite Map */}
      <div className="card" style={{ padding: 0, overflow: 'hidden', position: 'relative' }}>
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-2 text-sm font-bold text-main">
            <Activity size={14} className="text-primary" />
            Global Positioning Map
          </div>
          <div className="flex items-center gap-3">
            {[
              { role: 'CIVILIAN', label: 'Civilian', color: '#3b82f6' },
              { role: 'RESPONDER', label: 'Responder', color: '#10b981' },
              { role: 'INCIDENT_MANAGER', label: 'Manager', color: '#f59e0b' },
              { role: 'ADMIN', label: 'Admin', color: '#ef4444' },
            ].map(item => (
              <div key={item.role} className="flex items-center gap-1.5">
                <span
                  style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: item.color,
                    boxShadow: `0 0 6px ${item.color}80`,
                    display: 'inline-block',
                  }}
                />
                <span className="text-xs text-muted">{item.label}</span>
              </div>
            ))}
          </div>
        </div>

        {loading && (
          <div
            style={{
              position: 'absolute', inset: 0, zIndex: 1000,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'rgba(13,17,23,0.6)',
              pointerEvents: 'none'
            }}
          >
            <div className="flex flex-col items-center gap-2">
              <RefreshCw size={22} className="animate-spin text-primary" />
              <span className="text-xs text-muted">Updating map data...</span>
            </div>
          </div>
        )}

        <div style={{ height: '500px', width: '100%', position: 'relative' }}>
          <MapContainer 
            center={defaultCenter} 
            zoom={defaultZoom} 
            style={{ height: '100%', width: '100%', background: '#0d1117' }}
          >
            {/* Esri World Imagery (Satellite view) */}
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution='&copy; <a href="https://www.esri.com/">Esri</a>, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
            />
            
            {heatmap?.bounds && <MapBoundsFitter bounds={heatmap.bounds} />}

            {heatmap?.points.map(pt => (
              <CircleMarker
                key={pt.user_id}
                center={[pt.lat, pt.lng]}
                pathOptions={{
                  color: ROLE_COLORS[pt.role] ?? ROLE_COLORS.CIVILIAN,
                  fillColor: ROLE_COLORS[pt.role] ?? ROLE_COLORS.CIVILIAN,
                  fillOpacity: 0.6,
                  weight: 2
                }}
                radius={Math.max(6, 4 * pt.weight)}
              >
                <Popup className="dark-popup">
                  <div className="text-xs font-mono p-1">
                    <div className="font-bold mb-1 border-b border-gray-700 pb-1">@{pt.username}</div>
                    <div className="text-gray-400">Role: <span className="text-white">{pt.role}</span></div>
                    <div className="text-gray-400">Lat: <span className="text-white">{pt.lat.toFixed(6)}</span></div>
                    <div className="text-gray-400">Lng: <span className="text-white">{pt.lng.toFixed(6)}</span></div>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>

        {!loading && heatmap?.points.length === 0 && (
          <div
            style={{
              position: 'absolute',
              top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              textAlign: 'center',
              zIndex: 1000,
              background: 'rgba(13,17,23,0.85)',
              padding: '24px',
              borderRadius: '12px',
              border: '1px solid var(--border-subtle)'
            }}
          >
            <MapPin size={36} className="text-muted mx-auto mb-2 opacity-30" />
            <div className="text-sm font-semibold text-muted">No location data</div>
            <div className="text-xs text-muted mt-1">
              Users must allow GPS access in their browser.
            </div>
          </div>
        )}
      </div>

      {/* User Table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="flex items-center gap-2 text-sm font-bold text-main">
            <Users size={14} className="text-blue" />
            Active User Locations
            <span className="badge badge-outline text-muted">{users.length}</span>
          </div>
        </div>
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Full Name</th>
                <th>Role</th>
                <th>Latitude</th>
                <th>Longitude</th>
                <th>Accuracy (m)</th>
                <th>Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center p-8 text-muted">
                    <div className="flex flex-col items-center gap-2">
                      <MapPin size={22} className="opacity-20" />
                      <span className="text-sm">No users have shared their location in this window.</span>
                    </div>
                  </td>
                </tr>
              ) : (
                users.map(u => (
                  <tr key={u.id} className="hover:bg-surface-elevated transition-colors">
                    <td className="font-mono text-xs font-bold text-main">@{u.username}</td>
                    <td className="text-sm text-main">{u.full_name}</td>
                    <td>
                      <span className={`badge ${ROLE_BADGE[u.role] ?? 'badge-gray'}`}>
                        {u.role.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="font-mono text-xs">{u.latitude.toFixed(6)}°</td>
                    <td className="font-mono text-xs">{u.longitude.toFixed(6)}°</td>
                    <td className="font-mono text-xs">
                      {u.accuracy != null ? `±${u.accuracy.toFixed(0)}` : '—'}
                    </td>
                    <td className="text-xs text-muted font-mono">
                      {new Date(u.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

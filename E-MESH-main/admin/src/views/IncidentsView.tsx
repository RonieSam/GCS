import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Filter,
  RefreshCw,
  Search,
  Shield,
  User,
  X,
  Activity,
  MoreVertical,
  ChevronRight,
  Info
} from 'lucide-react';
import { api } from '../api/client';
import { Incident, Responder } from '../api/types';

import { useMeshEvent } from '../api/ws';

export const IncidentsView: React.FC = () => {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [responders, setResponders] = useState<Responder[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');

  // Selected incident modal
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [showDrawer, setShowDrawer] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [assignResponderId, setAssignResponderId] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const [incResp, respResp] = await Promise.all([
        api.getIncidents({
          search: search || undefined,
          status: statusFilter || undefined,
          priority: priorityFilter || undefined,
          page_size: 50,
        }),
        api.getResponders({ page_size: 100 }),
      ]);
      setIncidents(incResp.data);
      setTotal(incResp.total);
      setResponders(respResp.data);
    } catch (err) {
      console.error('Failed to load incidents', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter, priorityFilter]);

  useMeshEvent('incident.created', () => loadData());
  useMeshEvent('incident.updated', () => loadData());
  useMeshEvent('incident.assigned', () => loadData());
  useMeshEvent('incident.resolved', () => loadData());

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  const handleAcknowledge = async (id: string) => {
    setActionLoading(true);
    try {
      const updated = await api.acknowledgeIncident(id);
      setSelectedIncident(updated);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleResolve = async (id: string) => {
    setActionLoading(true);
    try {
      const updated = await api.resolveIncident(id, resolutionNotes || undefined);
      setSelectedIncident(updated);
      setResolutionNotes('');
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleAssignResponder = async (incidentId: string) => {
    if (!assignResponderId) return;
    setActionLoading(true);
    try {
      const updated = await api.assignIncident(incidentId, assignResponderId);
      setSelectedIncident(updated);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handlePriorityChange = async (incidentId: string, priority: string) => {
    setActionLoading(true);
    try {
      const updated = await api.updateIncident(incidentId, { priority });
      setSelectedIncident(updated);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStatusChange = async (incidentId: string, status: string) => {
    setActionLoading(true);
    try {
      const updated = await api.updateIncident(incidentId, { status });
      setSelectedIncident(updated);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const openDrawer = (inc: Incident) => {
    setSelectedIncident(inc);
    setShowDrawer(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Incidents & Triage</h2>
          <p className="text-sm text-muted mt-1">
            Manage, assign and resolve field reports ({total} total)
          </p>
        </div>
        <button onClick={loadData} disabled={loading} className="btn">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="widget bg-surface-elevated border-subtle p-3">
        <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-2 max-w-md">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Search descriptions, locations, categories..."
                className="form-input pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Filter size={14} className="text-muted" />
                <select className="form-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">All Statuses</option>
                  <option value="SUBMITTED">Submitted</option>
                  <option value="ACKNOWLEDGED">Acknowledged</option>
                  <option value="ASSIGNED">Assigned</option>
                  <option value="IN_PROGRESS">In Progress</option>
                  <option value="RESPONDING">Responding</option>
                  <option value="RESOLVED">Resolved</option>
                  <option value="CLOSED">Closed</option>
                  <option value="CANCELLED">Cancelled</option>
                </select>
            </div>

            <div className="flex items-center gap-2">
              <select className="form-select" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
                <option value="">All Priorities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
            </div>
          </div>
        </form>
      </div>

      {/* Incidents Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Priority</th>
              <th>Category</th>
              <th>Description</th>
              <th>People</th>
              <th>Assigned Responder</th>
              <th>Status</th>
              <th>Reported</th>
              <th className="actions"></th>
            </tr>
          </thead>
          <tbody>
            {incidents.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center p-8 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <CheckCircle size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No incidents match the current criteria.</span>
                  </div>
                </td>
              </tr>
            ) : (
              incidents.map((inc) => {
                const priorityColor =
                  inc.priority === 'CRITICAL' ? 'red' : inc.priority === 'HIGH' ? 'amber' : 'blue';

                const statusColor =
                  inc.status === 'SUBMITTED' ? 'amber' : inc.status === 'RESOLVED' ? 'emerald' : inc.status === 'CLOSED' ? 'gray' : 'blue';

                return (
                  <tr key={inc.id} onClick={() => openDrawer(inc)} className="hover:bg-surface-elevated cursor-pointer transition-colors">
                    <td>
                      <span className={`badge bg-${priorityColor} text-white`}>{inc.priority}</span>
                    </td>
                    <td className="font-semibold">{inc.category.replace(/_/g, ' ')}</td>
                    <td className="text-muted truncate max-w-xs">{inc.description}</td>
                    <td className="font-mono text-xs text-main">{inc.people_affected || 0}</td>
                    <td>
                      {inc.assigned_responder_id ? (
                        <div className="flex items-center gap-1 font-semibold text-blue">
                          <Shield size={12} />
                          {responders.find((r) => r.id === inc.assigned_responder_id)?.user?.full_name
                            || responders.find((r) => r.id === inc.assigned_responder_id)?.user?.username
                            || inc.assigned_responder_id.slice(0, 8)}
                        </div>
                      ) : (
                        <span className="text-muted text-xs italic">Unassigned</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge badge-outline text-${statusColor} border-${statusColor}`}>{inc.status.replace(/_/g, ' ')}</span>
                    </td>
                    <td className="font-mono text-xs text-muted">
                      {new Date(inc.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="actions">
                      <ChevronRight size={14} className="text-muted" />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Side Drawer for Details */}
      {showDrawer && selectedIncident && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowDrawer(false)}></div>
          <div className="drawer-panel" style={{ maxWidth: '480px' }}>
            <div className="drawer-header">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <AlertTriangle size={16} className={`text-${selectedIncident.priority === 'CRITICAL' ? 'red' : 'amber'}`} />
                Incident Details
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content space-y-6">
              {/* Header block */}
              <div className="flex items-start justify-between">
                <div>
                  <h4 className="text-xl font-bold text-main leading-tight mb-1">{selectedIncident.title}</h4>
                  <div className="font-mono text-xs text-blue">{selectedIncident.incident_id}</div>
                </div>
                <span className={`badge ${selectedIncident.status === 'RESOLVED' ? 'bg-emerald text-white' : 'badge-outline text-main'}`}>
                  {selectedIncident.status}
                </span>
              </div>

              {/* Attributes Grid */}
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <div className="text-xs font-semibold text-muted mb-1">Priority</div>
                  <select
                    className="form-select text-xs font-semibold p-1"
                    value={selectedIncident.priority}
                    onChange={(e) => handlePriorityChange(selectedIncident.id, e.target.value)}
                    disabled={actionLoading}
                  >
                    <option value="CRITICAL">CRITICAL</option>
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
                <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <div className="text-xs font-semibold text-muted mb-1">Category</div>
                  <div className="text-sm font-semibold text-main">{selectedIncident.category.replace(/_/g, ' ')}</div>
                </div>
                <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <div className="text-xs font-semibold text-muted mb-1">Reported At</div>
                  <div className="text-xs font-mono text-main">{new Date(selectedIncident.created_at).toLocaleString()}</div>
                </div>
                <div className="p-3 bg-surface-elevated border border-subtle rounded-sm">
                  <div className="text-xs font-semibold text-muted mb-1">People Affected</div>
                  <div className="text-sm font-semibold text-main">{selectedIncident.people_affected || 0}</div>
                </div>
              </div>

              {/* Description */}
              <div>
                <h5 className="text-xs font-bold uppercase tracking-widest text-muted mb-2">Description</h5>
                <div className="p-3 bg-surface-elevated border border-subtle rounded-sm text-sm text-main">
                  {selectedIncident.description}
                </div>
              </div>

              {/* Assignment */}
              <div>
                <h5 className="text-xs font-bold uppercase tracking-widest text-muted mb-2">Assignment</h5>
                <div className="flex items-center gap-2">
                  <select
                    className="form-select flex-1"
                    value={assignResponderId || selectedIncident.assigned_responder_id || ''}
                    onChange={(e) => setAssignResponderId(e.target.value)}
                    disabled={actionLoading}
                  >
                    <option value="">-- Unassigned --</option>
                    {responders.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.user?.full_name || r.user?.username || r.user_id.slice(0, 8)} ({r.status})
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => handleAssignResponder(selectedIncident.id)}
                    disabled={actionLoading || !assignResponderId || assignResponderId === selectedIncident.assigned_responder_id}
                    className="btn btn-primary"
                  >
                    Assign
                  </button>
                </div>
              </div>

              {/* Resolution Block */}
              {selectedIncident.status === 'RESOLVED' ? (
                <div>
                  <h5 className="text-xs font-bold uppercase tracking-widest text-emerald mb-2 flex items-center gap-1">
                    <CheckCircle size={12}/> Resolution Details
                  </h5>
                  <div className="p-3 bg-emerald/10 border border-emerald/20 rounded-sm text-sm text-main">
                    {selectedIncident.additional_info || 'No notes provided.'}
                    <div className="text-xs text-muted mt-2 font-mono">
                      Resolved: {selectedIncident.resolved_at ? new Date(selectedIncident.resolved_at).toLocaleString() : 'Unknown'}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="border-t border-subtle pt-6">
                  <h5 className="text-xs font-bold uppercase tracking-widest text-muted mb-2">Resolve Incident</h5>
                  <textarea
                    placeholder="Enter resolution notes before closing..."
                    className="form-textarea mb-3"
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                  />
                  <div className="flex gap-2">
                    {selectedIncident.status === 'SUBMITTED' && (
                      <button
                        onClick={() => handleAcknowledge(selectedIncident.id)}
                        disabled={actionLoading}
                        className="btn"
                      >
                        Acknowledge
                      </button>
                    )}
                    <button
                      onClick={() => handleResolve(selectedIncident.id)}
                      disabled={actionLoading}
                      className="btn btn-success flex-1"
                    >
                      Mark as Resolved
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

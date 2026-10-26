import React, { useEffect, useState } from 'react';
import {
  Edit2,
  MapPin,
  Plus,
  RefreshCw,
  Shield,
  Trash2,
  User,
  Users,
  X,
  Search,
  MoreVertical,
  ChevronRight
} from 'lucide-react';
import { api } from '../api/client';
import { Responder, ResponderStatus, User as UserType } from '../api/types';

export const RespondersView: React.FC = () => {
  const [responders, setResponders] = useState<Responder[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserType[]>([]);
  const [loading, setLoading] = useState(true);
  const [showDrawer, setShowDrawer] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Filter
  const [search, setSearch] = useState('');

  // Form
  const [selectedUserId, setSelectedUserId] = useState('');
  const [team, setTeam] = useState('Medical Rapid Response');
  const [zone, setZone] = useState('Zone Alpha (North)');

  const loadData = async () => {
    setLoading(true);
    try {
      const [respData, usersData] = await Promise.all([
        api.getResponders({ page_size: 100 }),
        api.getUsers({ page_size: 100 }),
      ]);
      setResponders(respData.data);
      setAvailableUsers(usersData.data);
    } catch (err) {
      console.error('Failed to load responders', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateResponder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUserId) return;
    setActionLoading(true);
    try {
      await api.createResponder({
        user_id: selectedUserId,
        team,
        zone,
      });
      setShowDrawer(false);
      setSelectedUserId('');
      await loadData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStatusChange = async (id: string, status: ResponderStatus) => {
    try {
      await api.updateResponder(id, { status });
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDeleteResponder = async (id: string) => {
    if (!confirm('Remove responder from field roster?')) return;
    try {
      await api.deleteResponder(id);
      await loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const filteredResponders = responders.filter(r => 
    (r.user?.full_name || '').toLowerCase().includes(search.toLowerCase()) ||
    (r.user?.username || '').toLowerCase().includes(search.toLowerCase()) ||
    (r.team || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Responder Roster</h2>
          <p className="text-sm text-muted mt-1">
            Dispatch teams, emergency roles, and operational readiness
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input 
              type="text" 
              placeholder="Filter roster..." 
              className="form-input pl-8" 
              style={{ width: '200px' }} 
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <button onClick={loadData} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => setShowDrawer(true)} className="btn btn-primary">
            <Plus size={14} /> Enlist
          </button>
        </div>
      </div>

      {/* Responders Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Personnel Name</th>
              <th>Username</th>
              <th>Assigned Team</th>
              <th>Operational Zone</th>
              <th className="actions"></th>
            </tr>
          </thead>
          <tbody>
            {filteredResponders.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center p-8 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <Shield size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No personnel found.</span>
                  </div>
                </td>
              </tr>
            ) : (
              filteredResponders.map((resp) => {
                const isAvailable = resp.status === 'AVAILABLE';
                const isBusy = resp.status === 'ASSIGNED' || resp.status === 'DEPLOYED' || resp.status === 'RESPONDING';
                const isUnavailable = resp.status === 'UNAVAILABLE' || resp.status === 'OFFLINE' || resp.status === 'RESTING';
                
                const dotColor = isAvailable ? 'emerald' : isBusy ? 'blue' : 'gray';

                return (
                  <tr key={resp.id} className="hover:bg-surface-elevated transition-colors">
                    <td>
                      <div className="flex items-center gap-2">
                        <select
                          className={`form-select text-xs font-semibold py-1 px-2 border-${dotColor} text-${dotColor} bg-transparent`}
                          style={{ width: '130px' }}
                          value={resp.status}
                          onChange={(e) => handleStatusChange(resp.id, e.target.value as ResponderStatus)}
                        >
                          <option value="AVAILABLE">AVAILABLE</option>
                          <option value="ASSIGNED">ASSIGNED</option>
                          <option value="RESPONDING">RESPONDING</option>
                          <option value="DEPLOYED">DEPLOYED</option>
                          <option value="BUSY">BUSY</option>
                          <option value="RESTING">RESTING</option>
                          <option value="UNAVAILABLE">UNAVAILABLE</option>
                          <option value="OFFLINE">OFFLINE</option>
                        </select>
                      </div>
                    </td>
                    <td className="font-bold text-main">{resp.user?.full_name || resp.user?.username || 'Unknown'}</td>
                    <td className="text-muted text-xs font-mono">@{resp.user?.username || resp.user_id.slice(0, 8)}</td>
                    <td className="font-semibold text-main">{resp.team || 'Unassigned'}</td>
                    <td className="text-muted">{resp.zone || 'General Area'}</td>
                    <td className="actions">
                      <button onClick={() => handleDeleteResponder(resp.id)} className="btn-icon hover:text-red hover:bg-red/5" title="Remove Responder">
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Add Drawer */}
      {showDrawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowDrawer(false)}></div>
          <div className="drawer-panel">
            <div className="drawer-header">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Shield size={16} className="text-primary" /> Enlist Responder
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content">
              <div className="bg-surface-elevated p-3 border border-subtle rounded-sm text-sm text-muted mb-4">
                Enlisting a user allows them to be dispatched to incidents and tracked via the NOC dashboard.
              </div>

              <form id="responder-form" onSubmit={handleCreateResponder} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Select Registered Account</label>
                  <select
                    required
                    className="form-select"
                    value={selectedUserId}
                    onChange={(e) => setSelectedUserId(e.target.value)}
                  >
                    <option value="">Choose a registered user...</option>
                    {availableUsers.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.full_name} (@{u.username}) — Role: {u.role}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Team Assignment</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Rapid Medical Unit, Hazmat"
                    className="form-input"
                    value={team}
                    onChange={(e) => setTeam(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Operational Zone</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Zone Alpha - Perimeter"
                    className="form-input"
                    value={zone}
                    onChange={(e) => setZone(e.target.value)}
                  />
                </div>
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">Cancel</button>
              <button type="submit" form="responder-form" disabled={actionLoading || !selectedUserId} className="btn btn-primary">
                {actionLoading ? 'Enlisting...' : 'Enlist Personnel'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

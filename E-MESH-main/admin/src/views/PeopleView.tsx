import React, { useEffect, useState } from 'react';
import {
  Check,
  Edit2,
  Plus,
  RefreshCw,
  Search,
  Shield,
  UserCheck,
  UserPlus,
  Users,
  UserX,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import { User, UserRole } from '../api/types';

export const PeopleView: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');

  // Modals
  const [showDrawer, setShowDrawer] = useState(false);

  // Form states
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('CIVILIAN');
  const [actionLoading, setActionLoading] = useState(false);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const resp = await api.getUsers({
        search: search || undefined,
        role: roleFilter || undefined,
        page_size: 100,
      });
      setUsers(resp.data);
      setTotal(resp.total);
    } catch (err) {
      console.error('Failed to load users', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, [roleFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadUsers();
  };

  const resetForm = () => {
    setUsername('');
    setFullName('');
    setEmail('');
    setPassword('');
    setRole('CIVILIAN');
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createUser({
        username,
        full_name: fullName,
        email: email || undefined,
        password,
        role,
      });
      setShowDrawer(false);
      resetForm();
      await loadUsers();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateRole = async (userId: string, newRole: UserRole) => {
    try {
      await api.updateUser(userId, { role: newRole });
      await loadUsers();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleToggleActive = async (user: User) => {
    try {
      if (user.is_active) {
        await api.deactivateUser(user.id);
      } else {
        await api.updateUser(user.id, { is_active: true });
      }
      await loadUsers();
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">People Directory</h2>
          <p className="text-sm text-muted mt-1">
            User access control, roles, and identity management ({total} registered)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={loadUsers} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={() => { resetForm(); setShowDrawer(true); }} className="btn btn-primary">
            <UserPlus size={14} /> Add User
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="widget bg-surface-elevated p-3 border-subtle">
        <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-2 max-w-md">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Search by full name, username, email..."
                className="form-input pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-bold tracking-widest uppercase">Role Filter</span>
            <select
              className="form-select text-xs py-1.5"
              style={{ width: '140px' }}
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="">All Roles</option>
              <option value="ADMIN">ADMIN</option>
              <option value="INCIDENT_MANAGER">INCIDENT_MANAGER</option>
              <option value="RESPONDER">RESPONDER</option>
              <option value="CIVILIAN">CIVILIAN</option>
              <option value="VIEWER">VIEWER</option>
            </select>
          </div>
        </form>
      </div>

      {/* Users Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Full Name</th>
              <th>Username</th>
              <th>Role</th>
              <th>Registered At</th>
              <th className="actions">Access Control</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <Users size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No users found matching criteria.</span>
                  </div>
                </td>
              </tr>
            ) : (
              users.map((u) => {
                const isSystemAdmin = u.role === 'ADMIN';

                return (
                  <tr key={u.id} className="hover:bg-surface-elevated transition-colors">
                    <td>
                      <div className="status-indicator">
                        <span className={`status-dot bg-${u.is_active ? 'emerald' : 'red'}`}></span>
                        <span className="text-xs uppercase font-semibold text-muted">{u.is_active ? 'Active' : 'Disabled'}</span>
                      </div>
                    </td>
                    <td className="font-bold text-main">{u.full_name}</td>
                    <td className="font-mono text-blue text-xs">@{u.username}</td>
                    <td>
                      <select
                        className={`form-select text-xs font-semibold py-1 px-2 border-subtle bg-transparent ${isSystemAdmin ? 'text-red' : 'text-main'}`}
                        style={{ width: '150px' }}
                        value={u.role}
                        onChange={(e) => handleUpdateRole(u.id, e.target.value as UserRole)}
                      >
                        <option value="ADMIN">ADMIN</option>
                        <option value="INCIDENT_MANAGER">INCIDENT_MANAGER</option>
                        <option value="RESPONDER">RESPONDER</option>
                        <option value="CIVILIAN">CIVILIAN</option>
                        <option value="VIEWER">VIEWER</option>
                      </select>
                    </td>
                    <td className="text-xs font-mono text-dim">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="actions">
                      <button
                        onClick={() => handleToggleActive(u)}
                        className={`btn btn-sm ${u.is_active ? 'text-red bg-red/5 hover:bg-red/10 border-transparent' : 'btn-primary'}`}
                      >
                        {u.is_active ? 'Deactivate' : 'Activate'}
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
                <UserPlus size={16} className="text-primary" /> Create Operator Account
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content">
              <form id="user-form" onSubmit={handleCreateUser} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Full Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. John Doe"
                    className="form-input"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Username (Unique ID)</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. jdoe_medic"
                    className="form-input font-mono"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Email Address (Optional)</label>
                  <input
                    type="email"
                    placeholder="e.g. jdoe@agency.gov"
                    className="form-input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Temporary Password</label>
                  <input
                    type="password"
                    required
                    placeholder="Min 6 characters"
                    className="form-input"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">System Access Role</label>
                  <select
                    className="form-select font-bold text-main"
                    value={role}
                    onChange={(e) => setRole(e.target.value as UserRole)}
                  >
                    <option value="CIVILIAN">CIVILIAN (No dashboard access)</option>
                    <option value="VIEWER">VIEWER (Read-only)</option>
                    <option value="RESPONDER">RESPONDER (Incident execution)</option>
                    <option value="INCIDENT_MANAGER">INCIDENT_MANAGER (Dispatch & control)</option>
                    <option value="ADMIN">ADMIN (Full network control)</option>
                  </select>
                </div>
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">Cancel</button>
              <button type="submit" form="user-form" disabled={actionLoading} className="btn btn-primary">
                {actionLoading ? 'Creating...' : 'Create Account'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

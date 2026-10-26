import React, { useEffect, useState } from 'react';
import {
  FileText,
  Filter,
  RefreshCw,
  Search,
  Shield,
  User,
} from 'lucide-react';
import { api } from '../api/client';
import { AuditLog } from '../api/types';

export const AuditLogView: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState('');

  const loadLogs = async () => {
    setLoading(true);
    try {
      const resp = await api.getAuditLogs({
        search: search || undefined,
        action: actionFilter || undefined,
        page_size: 100,
      });
      setLogs(resp.data);
      setTotal(resp.total);
    } catch (err) {
      console.error('Failed to load audit logs', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [actionFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadLogs();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Audit Log</h2>
          <p className="text-sm text-muted mt-1">
            System logs, operator actions, and compliance records ({total} entries)
          </p>
        </div>

        <button onClick={loadLogs} disabled={loading} className="btn">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh Trail
        </button>
      </div>

      {/* Filter Bar */}
      <div className="widget bg-surface-elevated p-3 border-subtle">
        <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-2 max-w-md">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Search audit actions, usernames, entity IDs, IP..."
                className="form-input pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-bold tracking-widest uppercase">Action Filter</span>
            <select
              className="form-select text-xs py-1.5"
              style={{ width: 'auto' }}
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
            >
              <option value="">All Actions</option>
              <option value="auth.login">auth.login</option>
              <option value="auth.logout">auth.logout</option>
              <option value="user.registered">user.registered</option>
              <option value="user.created">user.created</option>
              <option value="user.updated">user.updated</option>
              <option value="incident.created">incident.created</option>
              <option value="incident.updated">incident.updated</option>
              <option value="incident.acknowledged">incident.acknowledged</option>
              <option value="incident.resolved">incident.resolved</option>
              <option value="sos.created">sos.created</option>
              <option value="sos.updated">sos.updated</option>
              <option value="node.created">node.created</option>
              <option value="resource.created">resource.created</option>
              <option value="announcement.created">announcement.created</option>
            </select>
          </div>
        </form>
      </div>

      {/* Audit Log Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Action Key</th>
              <th>Operator / Actor</th>
              <th>Target Entity</th>
              <th>Client IP</th>
              <th>Metadata Context</th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <FileText size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No audit logs found matching criteria.</span>
                  </div>
                </td>
              </tr>
            ) : (
              logs.map((log) => {
                const isAuth = log.action.startsWith('auth.');
                const isCritical = log.action.includes('delete') || log.action.includes('deactivate');

                const actionColor = isCritical ? 'red' : isAuth ? 'emerald' : 'blue';

                const rawTime = log.timestamp || log.created_at;
                let formattedDate = '—';
                if (rawTime) {
                  const d = new Date(rawTime);
                  formattedDate = isNaN(d.getTime()) ? rawTime : d.toLocaleString();
                }

                let metaContent = '—';
                if (log.metadata) {
                  metaContent = typeof log.metadata === 'string' ? log.metadata : JSON.stringify(log.metadata);
                } else if (log.metadata_json) {
                  metaContent = log.metadata_json;
                }

                return (
                  <tr key={log.id} className="hover:bg-surface-elevated transition-colors">
                    <td className="font-mono text-xs text-dim whitespace-nowrap">
                      {formattedDate}
                    </td>
                    <td>
                      <span className={`badge bg-${actionColor}/10 text-${actionColor} border border-${actionColor}/20 font-mono`}>
                        {log.action}
                      </span>
                    </td>
                    <td>
                      <span className="font-semibold text-xs flex items-center gap-1.5 text-main">
                        <User size={12} className="text-muted" />
                        {log.actor_username || log.actor_id || 'System Anonymous'}
                      </span>
                    </td>
                    <td className="font-mono text-xs text-primary">
                      {log.entity_type ? `${log.entity_type} (${log.entity_id?.slice(0, 8)})` : 'N/A'}
                    </td>
                    <td className="font-mono text-xs text-muted">{log.ip_address || '127.0.0.1'}</td>
                    <td className="text-xs font-mono text-dim" style={{ maxWidth: '300px' }}>
                      <div className="truncate" title={metaContent}>
                        {metaContent}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

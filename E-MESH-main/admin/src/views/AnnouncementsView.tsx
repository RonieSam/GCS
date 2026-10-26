import React, { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Info,
  Megaphone,
  Plus,
  Radio,
  RefreshCw,
  Trash2,
  Volume2,
  X,
  Send
} from 'lucide-react';
import { api } from '../api/client';
import { Announcement, AnnouncementPriority } from '../api/types';

export const AnnouncementsView: React.FC = () => {
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [showDrawer, setShowDrawer] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Form
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [priority, setPriority] = useState<AnnouncementPriority>('INFO');

  const loadAnnouncements = async () => {
    setLoading(true);
    try {
      const resp = await api.getAnnouncements();
      setAnnouncements(resp.data);
    } catch (err) {
      console.error('Failed to load announcements', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnnouncements();
  }, []);

  const resetForm = () => {
    setTitle('');
    setMessage('');
    setPriority('INFO');
  };

  const handleCreateAnnouncement = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createAnnouncement({
        title,
        message,
        priority,
      });
      setShowDrawer(false);
      resetForm();
      await loadAnnouncements();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggleActive = async (id: string, current: boolean) => {
    try {
      await api.toggleAnnouncement(id, !current);
      await loadAnnouncements();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDeleteAnnouncement = async (id: string) => {
    if (!confirm('Permanently delete broadcast notice?')) return;
    try {
      await api.deleteAnnouncement(id);
      await loadAnnouncements();
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Emergency Broadcasts</h2>
          <p className="text-sm text-muted mt-1">
            Public advisories and shelter notices via mesh network ({announcements.length} total)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={loadAnnouncements} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={() => { resetForm(); setShowDrawer(true); }} className="btn btn-primary">
            <Plus size={14} /> New Broadcast
          </button>
        </div>
      </div>

      {/* Broadcast List */}
      <div className="flex flex-col gap-4">
        {announcements.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted gap-2 bg-surface-elevated border border-subtle rounded-md">
            <Megaphone size={32} className="opacity-30 mb-2" />
            <span className="font-bold">No announcements currently broadcasted.</span>
            <span className="text-sm">Click "New Broadcast" to issue an emergency notice.</span>
          </div>
        ) : (
          announcements.map((ann) => {
            const isCrit = ann.priority === 'CRITICAL';
            const isWarn = ann.priority === 'WARNING';
            const prioColor = isCrit ? 'red' : isWarn ? 'amber' : 'blue';

            return (
              <div
                key={ann.id}
                className="flex flex-col md:flex-row md:items-start justify-between gap-4 p-4 border border-subtle rounded-md transition-opacity"
                style={{
                  backgroundColor: ann.is_active ? 'var(--bg-surface)' : 'var(--bg-app)',
                  opacity: ann.is_active ? 1 : 0.6,
                  borderLeft: `4px solid var(--accent-${prioColor})`
                }}
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`badge bg-${prioColor} text-white`}>{ann.priority}</span>
                    <span className={`badge ${ann.is_active ? 'badge-outline text-emerald border-emerald' : 'badge-outline text-muted'}`}>
                      {ann.is_active ? 'BROADCASTING' : 'SUSPENDED'}
                    </span>
                    <span className="text-xs font-mono text-muted">
                      {new Date(ann.created_at).toLocaleString()}
                    </span>
                  </div>

                  <h3 className="text-lg font-bold text-main mt-1">{ann.title}</h3>
                  <p className="text-sm text-main mt-1.5 max-w-3xl leading-relaxed">{ann.message}</p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleToggleActive(ann.id, ann.is_active)}
                    className={`btn ${ann.is_active ? 'btn-danger' : 'btn-primary'}`}
                  >
                    {ann.is_active ? 'Suspend Broadcast' : 'Resume Broadcast'}
                  </button>
                  <button onClick={() => handleDeleteAnnouncement(ann.id)} className="btn-icon hover:text-red hover:bg-red/5" title="Delete">
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Side Drawer for Add */}
      {showDrawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setShowDrawer(false)}></div>
          <div className="drawer-panel">
            <div className="drawer-header">
              <h3 className="text-lg font-bold flex items-center gap-2">
                <Megaphone size={16} className="text-amber" /> Compose Mesh Broadcast
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content">
              <div className="bg-surface-elevated p-3 border border-subtle rounded-sm text-sm text-muted mb-4 flex gap-3">
                <Radio size={24} className="text-primary shrink-0"/>
                <span>Broadcasts are distributed via mesh packet flooding. All active nodes will repeat this message.</span>
              </div>

              <form id="broadcast-form" onSubmit={handleCreateAnnouncement} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Priority Level</label>
                  <div className="flex gap-2">
                    {(['INFO', 'WARNING', 'CRITICAL'] as const).map((p) => {
                      const color = p === 'CRITICAL' ? 'red' : p === 'WARNING' ? 'amber' : 'blue';
                      return (
                        <button
                          key={p}
                          type="button"
                          onClick={() => setPriority(p)}
                          className={`btn flex-1 ${priority === p ? `btn-primary bg-${color} border-${color}` : ''}`}
                        >
                          {p}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Notice Title</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Boil Water Advisory - Sector 3"
                    className="form-input font-bold"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Message Content</label>
                  <textarea
                    required
                    rows={6}
                    placeholder="Provide precise emergency instructions for civilians receiving this on the mesh..."
                    className="form-textarea"
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                  />
                </div>
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">Cancel</button>
              <button type="submit" form="broadcast-form" disabled={actionLoading} className="btn btn-primary">
                {actionLoading ? 'Transmitting...' : <><Send size={14}/> Transmit Over Mesh</>}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

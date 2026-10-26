import React, { useEffect, useState } from 'react';
import {
  Boxes,
  Edit2,
  Package,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
  MoreVertical
} from 'lucide-react';
import { api } from '../api/client';
import { ResourceItem, ResourceStatus } from '../api/types';

export const ResourcesView: React.FC = () => {
  const [resources, setResources] = useState<ResourceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  // Modals
  const [showDrawer, setShowDrawer] = useState(false);
  const [editItem, setEditItem] = useState<ResourceItem | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Form states
  const [name, setName] = useState('');
  const [resourceType, setResourceType] = useState('MEDICAL');
  const [quantity, setQuantity] = useState(10);
  const [availableQuantity, setAvailableQuantity] = useState(10);
  const [location, setLocation] = useState('Central Depot (Station 1)');
  const [status, setStatus] = useState<ResourceStatus>('AVAILABLE');

  const loadResources = async () => {
    setLoading(true);
    try {
      const resp = await api.getResources({
        search: search || undefined,
        resource_type: typeFilter || undefined,
        page_size: 100,
      });
      setResources(resp.data);
    } catch (err) {
      console.error('Failed to load resources', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadResources();
  }, [typeFilter]);

  const resetForm = () => {
    setEditItem(null);
    setName('');
    setResourceType('MEDICAL');
    setQuantity(10);
    setAvailableQuantity(10);
    setLocation('Central Depot (Station 1)');
    setStatus('AVAILABLE');
  };

  const handleCreateResource = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createResource({
        name,
        resource_type: resourceType,
        quantity,
        available_quantity: availableQuantity,
        location,
        status,
      });
      setShowDrawer(false);
      resetForm();
      await loadResources();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateResource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editItem) return;
    setActionLoading(true);
    try {
      await api.updateResource(editItem.id, {
        name,
        quantity,
        available_quantity: availableQuantity,
        location,
        status,
      });
      setShowDrawer(false);
      resetForm();
      await loadResources();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteResource = async (id: string, itemName: string) => {
    if (!confirm(`Delete asset "${itemName}" from inventory?`)) return;
    try {
      await api.deleteResource(id);
      await loadResources();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const openAdd = () => {
    resetForm();
    setShowDrawer(true);
  };

  const openEdit = (item: ResourceItem) => {
    setEditItem(item);
    setName(item.name);
    setResourceType(item.resource_type);
    setQuantity(item.quantity);
    setAvailableQuantity(item.available_quantity);
    setLocation(item.location || '');
    setStatus(item.status);
    setShowDrawer(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight">Asset Inventory</h2>
          <p className="text-sm text-muted mt-1">
            Emergency supplies, medical kits, and tracking ({resources.length} items)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={loadResources} disabled={loading} className="btn">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={openAdd} className="btn btn-primary">
            <Plus size={14} /> Add Asset
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="widget bg-surface-elevated p-3 border-subtle">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 items-center gap-2 max-w-md">
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                placeholder="Search resources, names, locations..."
                className="form-input pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && loadResources()}
              />
            </div>
            <button onClick={loadResources} className="btn btn-primary">Search</button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted font-bold tracking-widest uppercase">Asset Type</span>
            <select
              className="form-select text-xs py-1.5"
              style={{ width: 'auto' }}
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">All Types</option>
              <option value="MEDICAL">Medical Supplies</option>
              <option value="FOOD_WATER">Food & Water</option>
              <option value="POWER">Power & Generators</option>
              <option value="COMMUNICATIONS">Radio / Comms</option>
              <option value="RESCUE_GEAR">Rescue Gear</option>
            </select>
          </div>
        </div>
      </div>

      {/* Resource Table */}
      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Asset Name</th>
              <th>Category</th>
              <th>Available / Total</th>
              <th>Depot Location</th>
              <th>Last Updated</th>
              <th className="actions"></th>
            </tr>
          </thead>
          <tbody>
            {resources.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-12 text-muted">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <Package size={24} className="opacity-30" />
                    <span className="text-sm font-medium">No assets found in inventory.</span>
                  </div>
                </td>
              </tr>
            ) : (
              resources.map((item) => {
                const isLow = item.available_quantity <= item.quantity * 0.2;
                const badgeColor =
                  item.status === 'AVAILABLE' && !isLow
                    ? 'emerald'
                    : isLow || item.status === 'LOW_STOCK'
                    ? 'amber'
                    : 'red';

                return (
                  <tr key={item.id} className="hover:bg-surface-elevated cursor-pointer transition-colors" onClick={() => openEdit(item)}>
                    <td>
                      <div className="status-indicator">
                        <span className={`status-dot bg-${badgeColor}`}></span>
                        <span className="text-xs uppercase font-semibold text-muted">{isLow ? 'LOW STOCK' : item.status}</span>
                      </div>
                    </td>
                    <td className="font-bold text-main">{item.name}</td>
                    <td className="text-xs font-mono text-primary">{item.resource_type.replace(/_/g, ' ')}</td>
                    <td className="font-mono text-sm">
                      <span className={`font-bold ${isLow ? 'text-red' : 'text-emerald'}`}>{item.available_quantity}</span>
                      <span className="text-muted mx-1">/</span>
                      <span className="text-main">{item.quantity}</span>
                    </td>
                    <td className="text-xs text-muted">{item.location || 'N/A'}</td>
                    <td className="text-xs font-mono text-dim">
                      {new Date(item.updated_at).toLocaleDateString()}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => handleDeleteResource(item.id, item.name)} className="btn-icon hover:text-red hover:bg-red/5" title="Delete">
                          <Trash2 size={14} />
                        </button>
                        <button onClick={() => openEdit(item)} className="btn-icon" title="Edit Asset">
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
                <Boxes size={16} className="text-amber" /> {editItem ? 'Edit Asset' : 'Register New Asset'}
              </h3>
              <button onClick={() => setShowDrawer(false)} className="btn-icon"><X size={16} /></button>
            </div>

            <div className="drawer-content space-y-4">
              <form id="resource-form" onSubmit={editItem ? handleUpdateResource : handleCreateResource} className="space-y-4">
                <div className="form-group">
                  <label className="form-label">Asset Name</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Trauma Kit Type B"
                    className="form-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>

                {!editItem && (
                  <div className="form-group">
                    <label className="form-label">Category</label>
                    <select
                      className="form-select font-bold"
                      value={resourceType}
                      onChange={(e) => setResourceType(e.target.value)}
                    >
                      <option value="MEDICAL">Medical Supplies</option>
                      <option value="FOOD_WATER">Food & Water</option>
                      <option value="POWER">Power / Generator</option>
                      <option value="COMMUNICATIONS">Communications</option>
                      <option value="RESCUE_GEAR">Rescue Gear</option>
                    </select>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  <div className="form-group">
                    <label className="form-label">Total Inventory Count</label>
                    <input
                      type="number"
                      min="1"
                      className="form-input"
                      value={quantity}
                      onChange={(e) => setQuantity(parseInt(e.target.value))}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Currently Available</label>
                    <input
                      type="number"
                      min="0"
                      max={quantity}
                      className="form-input"
                      value={availableQuantity}
                      onChange={(e) => setAvailableQuantity(parseInt(e.target.value))}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Depot Location / Zone</label>
                  <input
                    type="text"
                    placeholder="e.g. North Station Depot"
                    className="form-input"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </div>

                {editItem && (
                  <div className="form-group">
                    <label className="form-label">Current Status</label>
                    <select
                      className="form-select"
                      value={status}
                      onChange={(e) => setStatus(e.target.value as ResourceStatus)}
                    >
                      <option value="AVAILABLE">AVAILABLE (In Stock)</option>
                      <option value="LOW_STOCK">LOW_STOCK (Needs Replenishment)</option>
                      <option value="DEPLETED">DEPLETED (Empty)</option>
                    </select>
                  </div>
                )}
              </form>
            </div>

            <div className="drawer-footer">
              <button type="button" onClick={() => setShowDrawer(false)} className="btn">Cancel</button>
              <button type="submit" form="resource-form" disabled={actionLoading} className="btn btn-primary">
                {actionLoading ? 'Saving...' : (editItem ? 'Save Asset' : 'Register Asset')}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

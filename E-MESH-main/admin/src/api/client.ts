import {
  AnalyticsMetrics,
  AnalyticsSummary,
  Announcement,
  AuditLog,
  CommunityMessage,
  HeatmapResponse,
  Incident,
  LocationUser,
  MeshNode,
  PaginatedResponse,
  ResourceItem,
  Responder,
  SimulatedLink,
  SimulatedNode,
  SimulationNetworkStatus,
  SimulationTopology,
  SOS,
  TimelineEvent,
  TopologyData,
  User,
} from './types';

const API_BASE = '/api/v1';

class ApiClient {
  private get token(): string | null {
    return localStorage.getItem('emesh_admin_access_token');
  }

  private get refreshToken(): string | null {
    return localStorage.getItem('emesh_admin_refresh_token');
  }

  public setTokens(access: string, refresh: string) {
    localStorage.setItem('emesh_admin_access_token', access);
    localStorage.setItem('emesh_admin_refresh_token', refresh);
  }

  public clearTokens() {
    localStorage.removeItem('emesh_admin_access_token');
    localStorage.removeItem('emesh_admin_refresh_token');
  }

  private async request<T>(endpoint: string, options: RequestInit = {}, isRetry = false): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    try {
      let response = await fetch(url, { ...options, headers });

      if (response.status === 401 && this.refreshToken && !isRetry) {
        const refreshed = await this.refreshTokens();
        if (refreshed) {
          headers['Authorization'] = `Bearer ${this.token}`;
          response = await fetch(url, { ...options, headers });
        } else {
          this.clearTokens();
          window.dispatchEvent(new Event('emesh:admin_auth_expired'));
          throw new Error('Session expired');
        }
      }

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        let errorMsg = `Error: ${response.status}`;
        if (data) {
          if (typeof data.detail === 'string') {
            errorMsg = data.detail;
          } else if (Array.isArray(data.detail)) {
            errorMsg = data.detail
              .map((err: any) => {
                const field = err.loc ? err.loc[err.loc.length - 1] : '';
                const cleanMsg = err.msg ? err.msg.replace(/^Value error,\s*/i, '') : 'Invalid value';
                return field ? `${field}: ${cleanMsg}` : cleanMsg;
              })
              .join(' | ');
          } else if (data.message) {
            errorMsg = data.message;
          }
        }
        throw new Error(errorMsg);
      }

      return data as T;
    } catch (err: any) {
      if (err.name === 'TypeError' && err.message.includes('fetch')) {
        throw new Error('Failed to communicate with E-Mesh Gateway');
      }
      throw err;
    }
  }

  private async refreshTokens(): Promise<boolean> {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: this.refreshToken }),
      });
      if (response.ok) {
        const data = await response.json();
        this.setTokens(data.access_token, data.refresh_token);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }

  // ── Auth ───────────────────────────────────────────────────────────────────
  public async login(username: string, password: string) {
    const data = await this.request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    this.setTokens(data.access_token, data.refresh_token);
    return data;
  }

  public async getMe(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  public async logout(): Promise<void> {
    try {
      await this.request('/auth/logout', { method: 'POST' });
    } catch {
      // offline ignore
    }
    this.clearTokens();
  }

  // ── Analytics ──────────────────────────────────────────────────────────────
  public async getAnalyticsSummary(): Promise<AnalyticsSummary> {
    return this.request<AnalyticsSummary>('/analytics/summary');
  }

  // ── Incidents ──────────────────────────────────────────────────────────────
  public async getIncidents(params?: {
    page?: number;
    page_size?: number;
    status?: string;
    priority?: string;
    category?: string;
    search?: string;
  }): Promise<PaginatedResponse<Incident>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.status) qs.append('status', params.status);
    if (params?.priority) qs.append('priority', params.priority);
    if (params?.category) qs.append('category', params.category);
    if (params?.search) qs.append('search', params.search);
    return this.request<PaginatedResponse<Incident>>(`/incidents?${qs.toString()}`);
  }

  public async updateIncident(
    id: string,
    payload: {
      status?: string;
      priority?: string;
      assigned_responder_id?: string | null;
      description?: string;
      people_affected?: number;
      location?: string;
    }
  ): Promise<Incident> {
    return this.request<Incident>(`/incidents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async acknowledgeIncident(id: string): Promise<Incident> {
    return this.request<Incident>(`/incidents/${id}/acknowledge`, { method: 'POST' });
  }

  public async assignIncident(id: string, responder_id: string): Promise<Incident> {
    return this.request<Incident>(`/incidents/${id}/assign`, {
      method: 'POST',
      body: JSON.stringify({ responder_id }),
    });
  }

  public async resolveIncident(id: string, notes?: string): Promise<Incident> {
    const body: Record<string, any> = { status: 'RESOLVED' };
    if (notes) body['additional_info'] = notes;
    return this.request<Incident>(`/incidents/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  // ── Community Group Chat ───────────────────────────────────────────────────
  public async getCommunityMessages(params?: { page?: number; page_size?: number }): Promise<PaginatedResponse<CommunityMessage>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    return this.request<PaginatedResponse<CommunityMessage>>(`/community/messages?${qs.toString()}`);
  }

  public async sendCommunityMessage(content: string): Promise<CommunityMessage> {
    return this.request<CommunityMessage>('/community/messages', {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  }

  // ── SOS ────────────────────────────────────────────────────────────────────
  public async getSOSList(params?: { page?: number; page_size?: number; status?: string }): Promise<PaginatedResponse<SOS>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.status) qs.append('status', params.status);
    return this.request<PaginatedResponse<SOS>>(`/sos?${qs.toString()}`);
  }

  public async updateSOS(id: string, payload: { status: string; incident_id?: string }): Promise<SOS> {
    return this.request<SOS>(`/sos/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  // ── Nodes & Topology ───────────────────────────────────────────────────────
  public async getNodes(params?: { page?: number; page_size?: number; status?: string }): Promise<PaginatedResponse<MeshNode>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.status) qs.append('status', params.status);
    return this.request<PaginatedResponse<MeshNode>>(`/nodes?${qs.toString()}`);
  }

  public async getNodeTelemetry(nodeId: string, limit: number = 50): Promise<any[]> {
    return this.request<any[]>(`/nodes/${nodeId}/telemetry?limit=${limit}`);
  }

  public async getTopology(): Promise<TopologyData> {
    return this.request<TopologyData>('/nodes/topology');
  }

  public async createNode(payload: {
    node_id: string;
    name: string;
    battery_level?: number;
    signal_quality?: number;
    hop_count?: number;
    firmware_version?: string;
  }): Promise<MeshNode> {
    return this.request<MeshNode>('/nodes', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateNode(
    id: string,
    payload: {
      name?: string;
      status?: string;
      battery_level?: number;
      signal_quality?: number;
      hop_count?: number;
    }
  ): Promise<MeshNode> {
    return this.request<MeshNode>(`/nodes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async deleteNode(id: string): Promise<void> {
    await this.request(`/nodes/${id}`, { method: 'DELETE' });
  }

  // ── Responders ─────────────────────────────────────────────────────────────
  public async getResponders(params?: { page?: number; page_size?: number; status?: string; team?: string }): Promise<PaginatedResponse<Responder>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.status) qs.append('status', params.status);
    if (params?.team) qs.append('team', params.team);
    return this.request<PaginatedResponse<Responder>>(`/responders?${qs.toString()}`);
  }

  public async createResponder(payload: { user_id: string; team?: string; zone?: string }): Promise<Responder> {
    return this.request<Responder>('/responders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateResponder(id: string, payload: { status?: string; team?: string; zone?: string }): Promise<Responder> {
    return this.request<Responder>(`/responders/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async deleteResponder(id: string): Promise<void> {
    await this.request(`/responders/${id}`, { method: 'DELETE' });
  }

  // ── Users / People ─────────────────────────────────────────────────────────
  public async getUsers(params?: { page?: number; page_size?: number; role?: string; search?: string }): Promise<PaginatedResponse<User>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.role) qs.append('role', params.role);
    if (params?.search) qs.append('search', params.search);
    return this.request<PaginatedResponse<User>>(`/users?${qs.toString()}`);
  }

  public async createUser(payload: {
    username: string;
    password: string;
    full_name: string;
    email?: string;
    role?: string;
  }): Promise<User> {
    return this.request<User>('/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateUser(id: string, payload: { role?: string; is_active?: boolean; full_name?: string; email?: string }): Promise<User> {
    return this.request<User>(`/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async deactivateUser(id: string): Promise<void> {
    await this.request(`/users/${id}`, { method: 'DELETE' });
  }

  // ── Resources ──────────────────────────────────────────────────────────────
  public async getResources(params?: { page?: number; page_size?: number; resource_type?: string; search?: string }): Promise<PaginatedResponse<ResourceItem>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.resource_type) qs.append('resource_type', params.resource_type);
    if (params?.search) qs.append('search', params.search);
    return this.request<PaginatedResponse<ResourceItem>>(`/resources?${qs.toString()}`);
  }

  public async createResource(payload: {
    resource_type: string;
    name: string;
    quantity: number;
    available_quantity?: number;
    location?: string;
    status?: string;
  }): Promise<ResourceItem> {
    return this.request<ResourceItem>('/resources', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async updateResource(
    id: string,
    payload: {
      name?: string;
      quantity?: number;
      available_quantity?: number;
      location?: string;
      status?: string;
    }
  ): Promise<ResourceItem> {
    return this.request<ResourceItem>(`/resources/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async deleteResource(id: string): Promise<void> {
    await this.request(`/resources/${id}`, { method: 'DELETE' });
  }

  // ── Announcements ──────────────────────────────────────────────────────────
  public async getAnnouncements(active_only?: boolean): Promise<PaginatedResponse<Announcement>> {
    let url = `/announcements?page_size=50`;
    if (active_only !== undefined) {
      url += `&active_only=${active_only}`;
    }
    return this.request<PaginatedResponse<Announcement>>(url);
  }

  public async createAnnouncement(payload: {
    title: string;
    message: string;
    priority?: string;
    target?: string;
  }): Promise<Announcement> {
    return this.request<Announcement>('/announcements', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async toggleAnnouncement(id: string, is_active: boolean): Promise<Announcement> {
    return this.request<Announcement>(`/announcements/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active }),
    });
  }

  public async deleteAnnouncement(id: string): Promise<void> {
    await this.request(`/announcements/${id}`, { method: 'DELETE' });
  }

  // ── ESP-WIFI-MESH Simulation Controls ────────────────────────────────────
  public async getSimulationNetworkStatus(): Promise<SimulationNetworkStatus> {
    return this.request<SimulationNetworkStatus>('/simulation/network-status');
  }

  public async getSimulationTopology(): Promise<SimulationTopology> {
    return this.request<SimulationTopology>('/simulation/topology');
  }

  public async getSimulationNodes(): Promise<SimulatedNode[]> {
    return this.request<SimulatedNode[]>('/simulation/nodes');
  }

  public async getSimulationNode(nodeId: string): Promise<SimulatedNode> {
    return this.request<SimulatedNode>(`/simulation/nodes/${nodeId}`);
  }

  public async getSimulationRoutes(): Promise<Record<string, string[]>> {
    return this.request<Record<string, string[]>>('/simulation/routes');
  }

  public async createSimulationNode(payload: {
    node_id: string;
    parent_id?: string | null;
    battery_percent?: number;
    rssi_dbm?: number;
    mac_address?: string;
  }): Promise<SimulatedNode> {
    return this.request<SimulatedNode>('/simulation/nodes', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async deleteSimulationNode(nodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/simulation/nodes/${nodeId}`, { method: 'DELETE' });
  }

  public async bringSimulationNodeOnline(nodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/simulation/nodes/${nodeId}/online`, { method: 'POST' });
  }

  public async takeSimulationNodeOffline(nodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/simulation/nodes/${nodeId}/offline`, { method: 'POST' });
  }

  public async restoreSimulationNode(nodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/simulation/nodes/${nodeId}/restore`, { method: 'POST' });
  }

  public async simulateNodeHeartbeat(nodeId: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/simulation/nodes/${nodeId}/heartbeat`, { method: 'POST' });
  }

  public async updateSimulationNode(
    nodeId: string,
    payload: {
      parent_id?: string | null;
      battery_percent?: number;
      rssi_dbm?: number;
      packet_loss_percent?: number;
      latency_ms?: number;
    }
  ): Promise<SimulatedNode> {
    return this.request<SimulatedNode>(`/simulation/nodes/${nodeId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  public async degradeSimulationLink(payload: {
    source_node_id: string;
    target_node_id: string;
    packet_loss_percent: number;
    latency_ms: number;
  }): Promise<{ message: string }> {
    return this.request<{ message: string }>('/simulation/links/degrade', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async getSimulationAnalytics(): Promise<AnalyticsMetrics> {
    return this.request<AnalyticsMetrics>('/simulation/analytics');
  }

  public async getSimulationTimeline(limit: number = 50): Promise<TimelineEvent[]> {
    return this.request<TimelineEvent[]>(`/simulation/timeline?limit=${limit}`);
  }

  public async failSimulationParent(payload: { parent_node_id: string; auto_reheal?: boolean }): Promise<any> {
    return this.request<any>('/simulation/fail-parent', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  public async failSimulationGateway(): Promise<any> {
    return this.request<any>('/simulation/fail-gateway', {
      method: 'POST',
    });
  }

  public async restoreSimulationNetwork(): Promise<any> {
    return this.request<any>('/simulation/restore-network', {
      method: 'POST',
    });
  }


  // ── Audit Logs ─────────────────────────────────────────────────────────────
  public async getAuditLogs(params?: { page?: number; page_size?: number; action?: string; search?: string }): Promise<PaginatedResponse<AuditLog>> {
    const qs = new URLSearchParams();
    if (params?.page) qs.append('page', params.page.toString());
    if (params?.page_size) qs.append('page_size', params.page_size.toString());
    if (params?.action) qs.append('action', params.action);
    if (params?.search) qs.append('search', params.search);
    return this.request<PaginatedResponse<AuditLog>>(`/audit-logs?${qs.toString()}`);
  }

  // ── Location / Heatmap ─────────────────────────────────────────────────────
  public async getHeatmapData(windowMinutes = 30): Promise<HeatmapResponse> {
    return this.request<HeatmapResponse>(`/location/heatmap?window_minutes=${windowMinutes}`);
  }

  public async getLocationUsers(windowMinutes = 30): Promise<LocationUser[]> {
    return this.request<LocationUser[]>(`/location/users?window_minutes=${windowMinutes}`);
  }
}

export const api = new ApiClient();

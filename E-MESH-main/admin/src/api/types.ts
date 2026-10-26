export type UserRole = 'ADMIN' | 'INCIDENT_MANAGER' | 'RESPONDER' | 'CIVILIAN' | 'VIEWER';

export type IncidentCategory =
  | 'MEDICAL'
  | 'FIRE_HAZARD'
  | 'STRUCTURAL_DAMAGE'
  | 'SECURITY'
  | 'SUPPLY_REQUEST'
  | 'SEARCH_AND_RESCUE'
  | 'OTHER';

export type IncidentPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type IncidentStatus =
  | 'SUBMITTED'
  | 'RECEIVED'
  | 'ACKNOWLEDGED'
  | 'ASSIGNED'
  | 'IN_PROGRESS'
  | 'RESPONDING'
  | 'RESOLVED'
  | 'CLOSED'
  | 'CANCELLED';

export type SOSStatus = 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED' | 'CANCELLED';

export type NodeStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED' | 'ISOLATED';

export type NodeLinkStatus = 'ACTIVE' | 'DEGRADED' | 'DOWN';

export type ResponderStatus =
  | 'AVAILABLE'
  | 'ASSIGNED'
  | 'RESPONDING'
  | 'UNAVAILABLE'
  | 'DEPLOYED'
  | 'BUSY'
  | 'RESTING'
  | 'OFFLINE';

export type ResourceStatus = 'AVAILABLE' | 'LOW_STOCK' | 'DEPLETED' | 'RESERVED';

export type AnnouncementPriority = 'INFO' | 'WARNING' | 'CRITICAL';

export type EventType =
  | 'sos.created'
  | 'incident.created'
  | 'incident.updated'
  | 'incident.assigned'
  | 'incident.resolved'
  | 'announcement.created'
  | 'node.online'
  | 'node.offline'
  | 'node.updated'
  | 'topology.updated'
  | 'route.changed'
  | 'system.alert'
  | 'user.location_updated'
  | 'community.message_sent';

export interface EventEnvelope<T = any> {
  id: string;
  event: EventType;
  timestamp: string;
  data: T;
  scope?: string | null;
}

export interface User {
  id: string;
  username: string;
  email?: string | null;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Incident {
  id: string;
  incident_id: string;
  title?: string | null;
  category: IncidentCategory;
  priority: IncidentPriority;
  status: IncidentStatus;
  description: string;
  people_affected: number;
  location?: string | null;
  additional_info?: string | null;
  reporter_id?: string | null;
  origin_node_id?: string | null;
  assigned_responder_id?: string | null;
  assigned_responder?: Responder | null;
  created_at: string;
  updated_at: string;
  acknowledged_at?: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
}

export interface CommunityMessage {
  id: string;
  sender_id?: string | null;
  sender_username: string;
  content: string;
  sent_at: string;
}

export interface SOS {
  id: string;
  reporter_id?: string | null;
  reporter?: User | null;
  node_id?: string | null;
  people_count: number;
  notes?: string | null;
  status: SOSStatus;
  incident_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MeshNode {
  id: string;
  node_id: string;
  name: string;
  status: NodeStatus;
  battery_percent?: number | null;
  rssi_dbm?: number | null;
  hop_count: number;
  firmware_version?: string | null;
  last_heartbeat?: string | null;
  current_route?: string | null;
  has_gps?: boolean;
  gps_lat?: number | null;
  gps_lon?: number | null;
  gps_alt_m?: number | null;
  gps_sats?: number | null;
  // Sensor telemetry (null when hardware not present)
  temperature_c?: number | null;
  pressure_hpa?: number | null;
  accel_x?: number | null;
  accel_y?: number | null;
  accel_z?: number | null;
  gyro_x?: number | null;
  gyro_y?: number | null;
  gyro_z?: number | null;
  created_at: string;
  updated_at: string;
}

export interface MeshNodeLink {
  id: string;
  source_node_id: string;
  target_node_id: string;
  rssi_dbm?: number | null;
  link_quality?: number;
  status: NodeLinkStatus;
  last_packet_at?: string | null;
}

export interface TopologyData {
  nodes: MeshNode[];
  links: MeshNodeLink[];
}

export interface Responder {
  id: string;
  user_id: string;
  user?: User | null;
  team?: string | null;
  status: ResponderStatus;
  zone?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResourceItem {
  id: string;
  resource_type: string;
  name: string;
  quantity: number;
  available_quantity: number;
  location?: string | null;
  status: ResourceStatus;
  created_at: string;
  updated_at: string;
}

export interface Announcement {
  id: string;
  title: string;
  message: string;
  priority: AnnouncementPriority;
  is_active: boolean;
  author_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  action: string;
  timestamp?: string;
  created_at?: string;
  actor_id?: string | null;
  actor_username?: string | null;
  actor_role?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  ip_address?: string | null;
  metadata_json?: string | null;
  metadata?: Record<string, any> | null;
}

export interface AnalyticsSummary {
  incidents: {
    total: number;
    active: number;
    resolved: number;
    by_priority: Record<string, number>;
    by_category: Record<string, number>;
  };
  sos: {
    total: number;
    active: number;
  };
  mesh: {
    total_nodes: number;
    online_nodes: number;
    offline_nodes: number;
    health_pct: number;
    avg_battery_pct: number;
  };
  responders: {
    total: number;
    available: number;
    deployed: number;
  };
  users: {
    total: number;
  };
  resources: {
    total_items: number;
  };
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SimulatedNode {
  node_id: string;
  mac_address: string;
  status: string;
  root_id: string;
  parent_id?: string | null;
  layer: number;
  children: string[];
  battery_percent?: number | null;
  rssi_dbm?: number | null;
  packet_loss_percent: number;
  latency_ms?: number | null;
  uptime_seconds: number;
  packets_received: number;
  packets_transmitted: number;
  last_heartbeat?: string | null;
  current_route: string[];
  position_x?: number | null;
  position_y?: number | null;
}

export interface SimulatedLink {
  source_node_id: string;
  target_node_id: string;
  rssi_dbm: number;
  packet_loss_percent: number;
  latency_ms: number;
  status: string;
  last_update?: string | null;
}

export interface SimulationNetworkStatus {
  mode: string;
  protocol_target: string;
  root_node_id: string;
  total_nodes: number;
  online_nodes: number;
  degraded_nodes: number;
  offline_nodes: number;
  max_tree_depth: number;
  active_links: number;
  uptime_seconds: number;
}

export interface SimulationTopology {
  root_id: string;
  nodes: SimulatedNode[];
  links: SimulatedLink[];
  max_depth: number;
}

export interface AnalyticsMetrics {
  total_nodes: number;
  online_nodes: number;
  degraded_nodes: number;
  offline_nodes: number;
  node_availability_percent: number;
  packet_delivery_ratio: number;
  packet_loss_percent: number;
  average_latency_ms: number;
  average_hop_count: number;
  topology_changes_count: number;
  latest_recovery_time_ms: number;
  average_recovery_time_ms: number;
  affected_nodes_count: number;
}

export interface TimelineEvent {
  timestamp: string;
  event_type: string;
  node_id: string;
  message: string;
  level: string;
}

export interface LocationPoint {
  lat: number;
  lng: number;
  weight: number;
  user_id: string;
  username: string;
  role: string;
  updated_at: string;
}

export interface HeatmapResponse {
  points: LocationPoint[];
  total_active: number;
  bounds: {
    min_lat: number;
    max_lat: number;
    min_lng: number;
    max_lng: number;
  } | null;
  generated_at: string;
}

export interface LocationUser {
  id: string;
  user_id: string;
  username: string;
  full_name: string;
  role: string;
  latitude: number;
  longitude: number;
  accuracy: number | null;
  updated_at: string;
}

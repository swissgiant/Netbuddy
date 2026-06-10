// Typed API client for the NetBuddy backend (proxied via Vite in dev).

export interface TopologyNode {
  id: string;
  label: string;
  type: "site" | "switch" | "firewall" | "router" | "ap" | "other";
  parent: string | null;
}
export interface TopologyEdge {
  source: string;
  target: string;
  type: "lldp" | "vpn";
  label?: string | null;
  up?: boolean | null;
}
export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface CapabilityStatus {
  capability: string;
  validated: boolean;
  last_status: string | null;
  last_checked_at: string | null;
  devices_checked: number;
}
export interface AdapterInfo {
  adapter_id: string;
  provenance: string | null;
  capabilities: CapabilityStatus[];
}

export interface Device {
  id: string;
  hostname: string;
  mgmt_ip: string;
  vendor: string;
  model: string | null;
  os_version: string | null;
  serial_number: string | null;
  device_type: string;
  adapter_id: string;
  site_id: string | null;
  enabled: boolean;
  last_seen: string | null;
}
export interface DeviceCreate {
  hostname: string;
  mgmt_ip: string;
  vendor: string;
  adapter_id: string;
  device_type?: string;
  model?: string | null;
  site_id?: string | null;
  credential_id?: string | null;
}

export interface Credential {
  id: string;
  name: string;
  username: string | null;
  ssh_port: number;
  base_url: string | null;
  kind: "ssh" | "telnet" | "api";
  created_at: string;
}
export interface CredentialCreate {
  name: string;
  username?: string | null;
  password?: string | null;
  enable_password?: string | null;
  ssh_port?: number;
  base_url?: string | null;
  api_token?: string | null;
  extra?: Record<string, unknown>;
}

export interface SiteSubnet {
  id: string;
  cidr: string;
  description: string | null;
}
export interface Site {
  id: string;
  name: string;
  code: string | null;
  description: string | null;
  mgmt_ip_template: string | null;
  subnets: SiteSubnet[];
}

export interface SuggestedDevice {
  key: string;
  sources: ("lldp" | "mac")[];
  name: string | null;
  dns_name: string | null;
  ip_address: string | null;
  ip_guessed: boolean;
  vendor: string | null;
  chassis_id: string | null;
  system_description: string | null;
  guessed_adapter: string | null;
  seen_on: string[];
}

export interface Interface {
  id: string;
  name: string;
  if_index: number | null;
  description: string | null;
  admin_status: "up" | "down" | "unknown";
  oper_status: "up" | "down" | "testing" | "unknown";
  mac_address: string | null;
  speed_mbps: number | null;
  mtu: number | null;
  interface_type: string | null;
  parent_name: string | null;
  vlan_id: number | null;
  last_polled: string | null;
}
export interface LldpNeighborRow {
  id: string;
  local_interface_id: string;
  remote_chassis_id: string;
  remote_port_id: string;
  remote_port_description: string | null;
  remote_system_name: string | null;
  remote_system_description: string | null;
  resolved_ip: string | null;
  resolved_name: string | null;
  guessed_vendor: string | null;
}
export interface MacEntry {
  id: string;
  interface_id: string;
  mac_address: string;
  vlan_id: number | null;
  entry_type: string;
}
export interface ArpEntry {
  id: string;
  ip_address: string;
  mac: string;
  vlan_id: number | null;
}
export interface DiscoveryRunResult {
  id: string;
  status: "running" | "success" | "partial" | "failed";
  triggered_by: string;
  devices_found: number;
  errors: { capability?: string; error: string }[];
  started_at: string;
  finished_at: string | null;
}
export interface CapabilityReport {
  capability: string;
  status: "ok" | "empty" | "error";
  row_count: number;
  coverage: Record<string, number>;
  message: string | null;
}
export interface ValidationReport {
  adapter_id: string;
  healthy: boolean;
  capabilities: CapabilityReport[];
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${init?.method ?? "GET"} ${path} → HTTP ${res.status} ${text}`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const fetchTopology = () => http<Topology>("/topology");
export const fetchAdapters = () => http<AdapterInfo[]>("/adapters");

export const fetchDevices = () => http<Device[]>("/devices");
export const createDevice = (body: DeviceCreate) =>
  http<Device>("/devices", { method: "POST", body: JSON.stringify(body) });
export const deleteDevice = (id: string) => http<void>(`/devices/${id}`, { method: "DELETE" });
export const updateDevice = (id: string, body: Partial<DeviceCreate>) =>
  http<Device>(`/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) });

// Read-only Live-Aktionen + Inventar-Lesesichten (Geräte-Detail).
export const discoverDevice = (id: string) =>
  http<DiscoveryRunResult>(`/devices/${id}/discover`, { method: "POST" });
export const validateDevice = (id: string) =>
  http<ValidationReport>(`/devices/${id}/validate`, { method: "POST" });
export const fetchInterfaces = (id: string) => http<Interface[]>(`/devices/${id}/interfaces`);
export const fetchMacTable = (id: string) => http<MacEntry[]>(`/devices/${id}/mac-table`);
export const fetchLldpNeighbors = (id: string) =>
  http<LldpNeighborRow[]>(`/devices/${id}/lldp-neighbors`);
export const fetchArp = (id: string) => http<ArpEntry[]>(`/devices/${id}/arp`);
export const backupDevice = (id: string) =>
  http<{ changed: boolean; sha256: string }>(`/devices/${id}/backup`, { method: "POST" });

export interface LldpStatus {
  supported: boolean;
  enabled: boolean | null;
}
export const lldpStatus = (id: string) =>
  http<LldpStatus>(`/devices/${id}/lldp/status`, { method: "POST" });
export interface LldpEnableResult {
  was_enabled: boolean;
  backed_up: boolean;
  interfaces_configured: number;
  enabled_after: boolean;
}
export const enableLldp = (id: string) =>
  http<LldpEnableResult>(`/devices/${id}/lldp/enable`, { method: "POST" });

export const fetchCredentials = () => http<Credential[]>("/credentials");
export const createCredential = (body: CredentialCreate) =>
  http<Credential>("/credentials", { method: "POST", body: JSON.stringify(body) });
export const deleteCredential = (id: string) =>
  http<void>(`/credentials/${id}`, { method: "DELETE" });

export const fetchSites = () => http<Site[]>("/sites");
export const createSite = (
  body: { name: string; code?: string; description?: string; mgmt_ip_template?: string },
) => http<Site>("/sites", { method: "POST", body: JSON.stringify(body) });
export const updateSite = (id: string, body: Partial<Omit<Site, "id">>) =>
  http<Site>(`/sites/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteSite = (id: string) => http<void>(`/sites/${id}`, { method: "DELETE" });
export const addSubnet = (siteId: string, cidr: string, description?: string) =>
  http<SiteSubnet>(`/sites/${siteId}/subnets`, {
    method: "POST",
    body: JSON.stringify({ cidr, description }),
  });
export const deleteSubnet = (siteId: string, subnetId: string) =>
  http<void>(`/sites/${siteId}/subnets/${subnetId}`, { method: "DELETE" });

export interface VpnTunnel {
  id: string;
  name: string;
  remote_gateway: string | null;
  is_up: boolean;
  relevant: boolean;
  local_subnets: string[];
  remote_subnets: string[];
}
export const fetchVpnTunnels = (deviceId: string) =>
  http<VpnTunnel[]>(`/devices/${deviceId}/vpn-tunnels`);
export const updateVpnTunnel = (deviceId: string, tunnelId: string, relevant: boolean) =>
  http<VpnTunnel>(`/devices/${deviceId}/vpn-tunnels/${tunnelId}`, {
    method: "PATCH",
    body: JSON.stringify({ relevant }),
  });

export const fetchSuggestions = () => http<SuggestedDevice[]>("/discovery/suggestions");

export interface LocateResult {
  kind: "host" | "mac" | "lldp";
  match: string;
  device_id: string;
  device_hostname: string;
  port: string;
  vlan: number | null;
  mac: string | null;
  ip_address: string | null;
  name: string | null;
  system_name: string | null;
  mgmt_address: string | null;
}
export const searchEndpoints = (q: string) =>
  http<LocateResult[]>(`/search?q=${encodeURIComponent(q)}`);

export interface ResolveHostsResult {
  hosts: number;
  resolved: number;
}
export const resolveHosts = () =>
  http<ResolveHostsResult>("/discovery/resolve-hosts", { method: "POST" });

export interface CrawlReport {
  seeds: number;
  discovered: string[];
  added: { hostname: string; mgmt_ip: string; adapter_id: string }[];
  errors: { device: string; error: string }[];
}
export const startCrawl = (
  seedDeviceIds: string[],
  credentialId: string,
  maxDepth: number,
  defaultAdapterId: string | null,
) =>
  http<CrawlReport>("/discovery/crawl", {
    method: "POST",
    body: JSON.stringify({
      seed_device_ids: seedDeviceIds,
      credential_id: credentialId,
      max_depth: maxDepth,
      default_adapter_id: defaultAdapterId,
    }),
  });

// --- Auth / Users ---

export interface AuthUser {
  id: string;
  username: string;
  role: "admin" | "operator" | "viewer";
  enabled: boolean;
}
export const fetchSetupStatus = () => http<{ setup_needed: boolean }>("/auth/setup-status");
export const authSetup = (username: string, password: string) =>
  http<{ token: string; user: AuthUser }>("/auth/setup", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
export const authLogin = (username: string, password: string) =>
  http<{ token: string; user: AuthUser }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
export const authLogout = () => http<void>("/auth/logout", { method: "POST" });
export const fetchMe = () => http<AuthUser>("/auth/me");

export const fetchUsers = () => http<AuthUser[]>("/users");
export const createUser = (username: string, password: string, role: string) =>
  http<AuthUser>("/users", { method: "POST", body: JSON.stringify({ username, password, role }) });
export const deleteUser = (id: string) => http<void>(`/users/${id}`, { method: "DELETE" });

export interface DeviceCredentialRow {
  device_id: string;
  credential_id: string;
  protocol: string;
  credential_name: string;
  kind: "ssh" | "telnet" | "api";
}
export const fetchDeviceCredentials = () => http<DeviceCredentialRow[]>("/device-credentials");
export const linkCredential = (deviceId: string, credentialId: string, protocol = "ssh") =>
  http<unknown>(`/devices/${deviceId}/credentials`, {
    method: "POST",
    body: JSON.stringify({ credential_id: credentialId, protocol }),
  });
export const unlinkCredential = (deviceId: string, credentialId: string, protocol = "ssh") =>
  http<void>(`/devices/${deviceId}/credentials/${credentialId}?protocol=${protocol}`, {
    method: "DELETE",
  });

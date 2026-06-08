// Typed API client for the NetBuddy backend (proxied via Vite in dev).

export interface TopologyNode {
  id: string;
  label: string;
  type: "site" | "switch" | "firewall" | "router" | "ap" | "other";
  site_id: string | null;
}
export interface TopologyEdge {
  source: string;
  target: string;
  type: "member" | "lldp";
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

export interface Site {
  id: string;
  name: string;
  code: string | null;
  description: string | null;
}

export interface SuggestedDevice {
  system_name: string | null;
  chassis_id: string;
  remote_port_id: string;
  system_description: string | null;
  seen_on: string[];
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

export const fetchCredentials = () => http<Credential[]>("/credentials");
export const createCredential = (body: CredentialCreate) =>
  http<Credential>("/credentials", { method: "POST", body: JSON.stringify(body) });
export const deleteCredential = (id: string) =>
  http<void>(`/credentials/${id}`, { method: "DELETE" });

export const fetchSites = () => http<Site[]>("/sites");
export const createSite = (body: { name: string; code?: string }) =>
  http<Site>("/sites", { method: "POST", body: JSON.stringify(body) });

export const fetchSuggestions = () => http<SuggestedDevice[]>("/discovery/suggestions");

export interface LocateResult {
  kind: "mac" | "lldp";
  match: string;
  device_id: string;
  device_hostname: string;
  port: string;
  vlan: number | null;
  mac: string | null;
  system_name: string | null;
  mgmt_address: string | null;
}
export const searchEndpoints = (q: string) =>
  http<LocateResult[]>(`/search?q=${encodeURIComponent(q)}`);

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

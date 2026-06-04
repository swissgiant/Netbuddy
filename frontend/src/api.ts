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

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

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const fetchTopology = () => getJson<Topology>("/topology");
export const fetchAdapters = () => getJson<AdapterInfo[]>("/adapters");

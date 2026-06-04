import { useEffect, useMemo, useState } from "react";
import type { AdapterInfo, Topology } from "../api";
import { fetchAdapters, fetchTopology } from "../api";
import { TopologyGraph } from "../TopologyGraph";

const NODE_LAYERS = ["site", "switch", "firewall", "router", "ap", "other"] as const;
const EDGE_LAYERS = ["member", "lldp"] as const;

export function TopologyView({ theme }: { theme: "dark" | "light" }) {
  const [topology, setTopology] = useState<Topology | null>(null);
  const [adapters, setAdapters] = useState<AdapterInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nodeLayers, setNodeLayers] = useState<Set<string>>(new Set(NODE_LAYERS));
  const [edgeLayers, setEdgeLayers] = useState<Set<string>>(new Set(EDGE_LAYERS));

  const reload = () => {
    fetchTopology().then(setTopology).catch((e) => setError(String(e)));
    fetchAdapters().then(setAdapters).catch(() => {});
  };
  useEffect(reload, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    topology?.nodes.forEach((n) => (c[n.type] = (c[n.type] ?? 0) + 1));
    return c;
  }, [topology]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setter(next);
  };

  return (
    <div className="topo">
      <aside className="controls">
        <button className="ghost" onClick={reload}>↻ Neu laden</button>
        {error && <p className="error">{error}</p>}

        <h3>Layer — Geräte</h3>
        {NODE_LAYERS.map((t) => (
          <label key={t} style={{ display: "block" }}>
            <input type="checkbox" checked={nodeLayers.has(t)} onChange={() => toggle(nodeLayers, setNodeLayers, t)} />{" "}
            {t} {counts[t] ? `(${counts[t]})` : ""}
          </label>
        ))}

        <h3>Layer — Verbindungen</h3>
        {EDGE_LAYERS.map((t) => (
          <label key={t} style={{ display: "block" }}>
            <input type="checkbox" checked={edgeLayers.has(t)} onChange={() => toggle(edgeLayers, setEdgeLayers, t)} />{" "}
            {t === "member" ? "Standort-Zugehörigkeit" : "LLDP-Links"}
          </label>
        ))}

        <h3>Adapter-Status</h3>
        {adapters.map((a) => (
          <div key={a.adapter_id} style={{ fontSize: 12, marginBottom: 6 }}>
            <strong>{a.adapter_id}</strong>
            <br />
            {a.capabilities.map((c) => (
              <span key={c.capability} title={`${c.capability}: ${c.validated ? "validiert" : "offen"}`}>
                {c.validated ? "✅" : "⬜"}
              </span>
            ))}
          </div>
        ))}
      </aside>

      <div className="graph">
        {topology ? (
          <TopologyGraph topology={topology} visibleNodeTypes={nodeLayers} visibleEdgeTypes={edgeLayers} theme={theme} />
        ) : (
          <p style={{ padding: 16 }}>Lade Topologie…</p>
        )}
      </div>
    </div>
  );
}

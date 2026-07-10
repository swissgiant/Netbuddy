// Reine Element-/Layout-Berechnung für die VLAN-Topologie (S64) — deterministisch, testbar.
// Kein Cytoscape-Import: Ausgabe sind einfache Element-Definitionen mit festen Positionen
// (preset-Layout). Das frühere cose-Layout kollabierte mit Compound-Knoten zu einem leeren
// Container — deshalb rechnen wir das Raster selbst.

export interface SurveyVlanIn {
  vlan_id: number;
  names: string[];
  gateways: { device: string; ip: string }[];
  dhcp_servers: string[];
  dhcp_helpers: { device: string; helpers: string[] }[];
  carriers: string[];
  access_ports: number;
}
export interface TransitionIn {
  vlan_id: number;
  to: string;
  detail: string | null;
  policy: string | null;
  device: string;
}
export interface SurveyDataIn {
  sites: Record<string, SurveyVlanIn[]>;
  transitions?: Record<string, TransitionIn[]>;
}

export interface ElementDef {
  data: Record<string, string | number | undefined>;
  position?: { x: number; y: number };
}

// Layout-Konstanten (px im Cytoscape-Koordinatenraum)
const NODE_W = 128;
const NODE_H = 56;
const GAP_X = 30;
const GAP_Y = 40;
const SITE_PAD = 60;
const SITE_GAP = 120;
const ROW_LIMIT = 2600; // maximale Zeilenbreite, danach nächste Site-Zeile

export function vlanColor(vid: number, names: string[]): string {
  const n = names.join(" ").toLowerCase();
  if (n.includes("gäste") || n.includes("gaeste") || n.includes("guest")) return "#f59e0b";
  if (n.includes("aufsetz")) return "#a855f7";
  if (vid >= 101 && vid <= 116) return "#06b6d4";
  if (vid === 1) return "#64748b";
  return "#3b82f6";
}

export function buildVlanTopoElements(data: SurveyDataIn): ElementDef[] {
  const elements: ElementDef[] = [];
  const transitions = data.transitions ?? {};
  const vlanNode = (site: string, vid: number) => `v:${site}:${vid}`;
  const haveVlan = new Set<string>();

  // Site-Blöcke vorbereiten: Grid-Maße pro Site aus der VLAN-Anzahl.
  const sites = Object.entries(data.sites).sort(([a], [b]) => a.localeCompare(b));
  const blocks = sites.map(([site, vlans]) => {
    const hasInet = (transitions[site] ?? []).some((t) => t.to === "internet");
    const hasLan = (transitions[site] ?? []).some((t) => t.to === "lan");
    const cols = Math.max(2, Math.ceil(Math.sqrt(vlans.length || 1)));
    const rows = Math.ceil((vlans.length || 1) / cols);
    const extraRows = (hasInet ? 1 : 0) + (hasLan ? 1 : 0);
    const w = cols * (NODE_W + GAP_X) - GAP_X + 2 * SITE_PAD;
    const h = (rows + extraRows) * (NODE_H + GAP_Y) - GAP_Y + 2 * SITE_PAD;
    return { site, vlans, hasInet, hasLan, cols, w, h };
  });

  // Sites zeilenweise packen (deterministisch, alphabetisch).
  let cursorX = 0;
  let cursorY = 0;
  let rowMaxH = 0;
  for (const b of blocks) {
    if (cursorX > 0 && cursorX + b.w > ROW_LIMIT) {
      cursorX = 0;
      cursorY += rowMaxH + SITE_GAP;
      rowMaxH = 0;
    }
    const originX = cursorX + SITE_PAD;
    let y = cursorY + SITE_PAD;
    elements.push({ data: { id: `site:${b.site}`, label: b.site, kind: "site" } });

    if (b.hasInet) {
      elements.push({
        data: { id: `inet:${b.site}`, parent: `site:${b.site}`, label: "🌍 Internet", kind: "inet" },
        position: { x: originX + (b.w - 2 * SITE_PAD) / 2, y },
      });
      y += NODE_H + GAP_Y;
    }
    b.vlans.forEach((v, i) => {
      const col = i % b.cols;
      const row = Math.floor(i / b.cols);
      const id = vlanNode(b.site, v.vlan_id);
      haveVlan.add(id);
      const name = v.names[0] ?? "";
      const gw = v.gateways[0]?.ip ?? "";
      elements.push({
        data: {
          id,
          parent: `site:${b.site}`,
          label: `VLAN ${v.vlan_id}${name ? `\n${name}` : ""}${gw ? `\n${gw}` : ""}`,
          kind: "vlan",
          color: vlanColor(v.vlan_id, v.names),
        },
        position: {
          x: originX + col * (NODE_W + GAP_X),
          y: y + row * (NODE_H + GAP_Y),
        },
      });
    });
    const vlanRows = Math.ceil((b.vlans.length || 1) / b.cols);
    if (b.hasLan) {
      elements.push({
        data: { id: `lan:${b.site}`, parent: `site:${b.site}`, label: `LAN ${b.site}`, kind: "lan" },
        position: {
          x: originX + (b.w - 2 * SITE_PAD) / 2,
          y: y + vlanRows * (NODE_H + GAP_Y),
        },
      });
    }
    cursorX += b.w + SITE_GAP;
    rowMaxH = Math.max(rowMaxH, b.h);
  }

  // Kanten aus den Übergängen.
  const vpnByVlan: Record<number, Set<string>> = {};
  const edgeIds = new Set<string>();
  const addEdge = (id: string, source: string, target: string, ekind: string, elabel = "") => {
    if (edgeIds.has(id) || !haveVlan.has(source)) return;
    edgeIds.add(id);
    elements.push({ data: { id, source, target, ekind, elabel } });
  };
  for (const [site, ts] of Object.entries(transitions)) {
    for (const t of ts) {
      const src = vlanNode(site, t.vlan_id);
      if (!haveVlan.has(src)) continue;
      if (t.to === "internet") {
        addEdge(`${src}->inet`, src, `inet:${site}`, "inet");
      } else if (t.to === "lan") {
        addEdge(`${src}->lan`, src, `lan:${site}`, "lan");
      } else if (t.to === "vlan" && t.detail) {
        const dst = vlanNode(site, Number(t.detail));
        if (haveVlan.has(dst) && src !== dst) addEdge(`${src}->${dst}`, src, dst, "vlan");
      } else if (t.to === "vpn") {
        (vpnByVlan[t.vlan_id] ??= new Set()).add(site);
      }
    }
  }
  for (const [vidStr, siteSet] of Object.entries(vpnByVlan)) {
    const uniq = [...siteSet].sort();
    for (let i = 0; i < uniq.length; i++) {
      for (let j = i + 1; j < uniq.length; j++) {
        const a = vlanNode(uniq[i], Number(vidStr));
        const b = vlanNode(uniq[j], Number(vidStr));
        if (haveVlan.has(a) && haveVlan.has(b)) {
          addEdge(`${a}<->${b}`, a, b, "vpn", "VPN");
        }
      }
    }
  }
  return elements;
}

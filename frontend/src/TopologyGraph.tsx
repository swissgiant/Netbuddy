import cytoscape from "cytoscape";
import { useEffect, useRef } from "react";
import type { Topology } from "./api";
import { NODE_ICON } from "./nodeIcons";

// Farbe je Knoten-Typ.
const NODE_COLOR: Record<string, string> = {
  site: "#6b7280",
  switch: "#2563eb",
  firewall: "#dc2626",
  router: "#7c3aed",
  ap: "#059669",
  unknown: "#94a3b8",
  other: "#9ca3af",
  endpoint: "#f59e0b",
};

// Ephemerer Endgerät-Knoten (nur bei Suche eingeblendet).
export interface EndpointHighlight {
  id: string;
  label: string;
  deviceId: string; // Switch, an dem es hängt (device:<uuid>-Knoten)
  port: string;
}

interface Props {
  topology: Topology;
  // sichtbare Layer (Knoten-Typen + Kanten-Typen), vom Parent gesteuert
  visibleNodeTypes: Set<string>;
  visibleEdgeTypes: Set<string>;
  theme: "dark" | "light";
  fontSize: number;
  edgeWidth: number;
  edgeColor: string;
  endpoints: EndpointHighlight[];
  layoutNonce: number; // ändert sich → Layout neu aufbauen ("Layout aufräumen")
}

const labelColor = (theme: "dark" | "light") => (theme === "dark" ? "#e2e8f0" : "#0f172a");

// Strukturiertes, deterministisches Layout (kein Force-Chaos): jeder Standort ist ein
// horizontales Band; darin oben die Backbone (Firewall/Router), darunter je Switch eine Gruppe
// mit seinen APs als kompaktes Grid. So hängen APs sichtbar + kurz an ihrem Switch.
type XY = { x: number; y: number };

export function computeStructuredPositions(topo: Topology): Record<string, XY> {
  const AP_DX = 64,
    AP_DY = 64,
    SW_H = 72,
    GROUP_GAP = 44,
    STACK_GAP = 12, // Abstand zwischen Stack-Membern (eine Einheit)
    ROW_GAP = 72,
    SITE_GAP = 120; // Abstand zwischen Standort-Boxen

  const nodeType: Record<string, string> = {};
  for (const n of topo.nodes) nodeType[n.id] = n.type;

  // AP → sein Switch: aus Uplink- und (für Waisen) inferierten AP-Kanten.
  const switchOfAp: Record<string, string> = {};
  for (const e of topo.edges)
    if ((e.type === "uplink" || e.type === "inferred") && nodeType[e.source] === "ap")
      switchOfAp[e.source] = e.target;
  // Mesh-APs (drahtlose AP→AP-Kante) zum Switch des Eltern-APs gruppieren, damit sie nah daran liegen.
  for (const e of topo.edges)
    if (e.type === "wireless" && nodeType[e.source] === "ap" && switchOfAp[e.target])
      switchOfAp[e.source] = switchOfAp[e.target];

  // Infrastruktur-Graph (Switch/Firewall/Router/Unbekannt) aus echten Kanten: lldp/uplink/
  // inferred = Hierarchie-Kanten, stack = gleiche Ebene (ein logischer Switch).
  const INFRA = new Set(["switch", "firewall", "router", "unknown"]);
  const isInfra = (id: string) => INFRA.has(nodeType[id]);
  const adj: Record<string, Set<string>> = {};
  const stackAdj: Record<string, Set<string>> = {};
  const link = (m: Record<string, Set<string>>, a: string, b: string) => {
    (m[a] ??= new Set()).add(b);
    (m[b] ??= new Set()).add(a);
  };
  for (const e of topo.edges) {
    if (!isInfra(e.source) || !isInfra(e.target) || e.source === e.target) continue;
    if (e.type === "stack") link(stackAdj, e.source, e.target);
    else if (e.type === "lldp" || e.type === "uplink" || e.type === "inferred")
      link(adj, e.source, e.target);
  }
  const coreIds = new Set<string>();
  const distIds = new Set<string>();
  for (const n of topo.nodes) {
    if (n.type !== "switch") continue;
    if (n.role === "core" || (n.label || "").toLowerCase().includes("core")) coreIds.add(n.id);
    else if (n.role === "distribution") distIds.add(n.id);
  }

  type N = (typeof topo.nodes)[number];
  type Bucket = { infra: N[]; apsBySwitch: Record<string, N[]>; loose: N[] };
  const buckets: Record<string, Bucket> = {};
  const bucket = (id: string) => (buckets[id] ??= { infra: [], apsBySwitch: {}, loose: [] });
  const siteOrder = topo.nodes.filter((n) => n.type === "site").map((n) => n.id);

  for (const n of topo.nodes) {
    if (n.type === "site") continue;
    const b = bucket(n.parent ?? "site:none");
    if (INFRA.has(n.type)) b.infra.push(n);
    else if (n.type === "ap" && switchOfAp[n.id]) (b.apsBySwitch[switchOfAp[n.id]] ??= []).push(n);
    else b.loose.push(n);
  }

  const byLabel = (a: { label: string }, c: { label: string }) => a.label.localeCompare(c.label);

  // Phase 1: Layout EINES Standorts als echter Baum von oben nach unten (Reingold-Tilford-
  // artig). Einheit („Unit") = ein Switch oder ein ganzer Stack (Member nebeneinander, ein
  // logischer Switch). Wurzeln = Firewall/Router, sonst Core, sonst Distribution, sonst der
  // Switch mit den meisten Switch-Nachbarn. Kinder = per LLDP/Uplink erreichte Units,
  // zentriert unter ihrer Uplink-Unit; jeder Switch trägt seine APs als Grid darunter. Darunter
  // ein zweiter Baum unter „Unbekannter Switch" (Waisen), dann nicht angebundene Infrastruktur
  // und lose APs.
  function layoutSite(b: Bucket): { local: Record<string, XY>; w: number; h: number } {
    const local: Record<string, XY> = {};
    const label: Record<string, string> = {};
    for (const n of b.infra) label[n.id] = n.label;
    const infraIds = new Set(b.infra.map((n) => n.id));
    const byLbl = (p: string, q: string) => label[p].localeCompare(label[q]);

    const apCols = (id: string) => {
      const aps = b.apsBySwitch[id] ?? [];
      return Math.min(5, Math.max(1, Math.ceil(Math.sqrt(aps.length || 1))));
    };
    const groupW = (id: string) => Math.max(AP_DX, apCols(id) * AP_DX);
    const groupH = (id: string) => {
      const aps = b.apsBySwitch[id] ?? [];
      return SW_H + Math.ceil((aps.length || 1) / apCols(id)) * AP_DY;
    };

    // Units: Stack-Member (verbunden über stack-Kanten) zu einer Einheit zusammenfassen.
    const unitOf: Record<string, number> = {};
    const units: string[][] = [];
    for (const n of b.infra.slice().sort(byLabel)) {
      if (unitOf[n.id] !== undefined) continue;
      const members: string[] = [];
      const stack = [n.id];
      unitOf[n.id] = units.length;
      while (stack.length) {
        const x = stack.pop() as string;
        members.push(x);
        for (const y of stackAdj[x] ?? [])
          if (infraIds.has(y) && unitOf[y] === undefined) {
            unitOf[y] = units.length;
            stack.push(y);
          }
      }
      units.push(members.sort(byLbl));
    }
    const unitAdj: Set<number>[] = units.map(() => new Set<number>());
    for (const u of units.keys())
      for (const m of units[u])
        for (const y of adj[m] ?? []) {
          const v = unitOf[y];
          if (v !== undefined && v !== u) {
            unitAdj[u].add(v);
            unitAdj[v].add(u);
          }
        }
    const unitLabel = (u: number) => label[units[u][0]];
    const unitDegree = (u: number) => unitAdj[u].size;

    // Baum aus Wurzel-Units per BFS.
    const depth: Record<number, number> = {};
    const parent: Record<number, number | null> = {};
    const children: Record<number, number[]> = {};
    const visit = (roots: number[]) => {
      const queue: number[] = [];
      for (const r of roots) {
        if (depth[r] !== undefined) continue;
        depth[r] = 0;
        parent[r] = null;
        queue.push(r);
      }
      while (queue.length) {
        const x = queue.shift() as number;
        for (const y of [...unitAdj[x]].sort((p, q) => unitLabel(p).localeCompare(unitLabel(q)))) {
          if (depth[y] !== undefined) continue;
          depth[y] = depth[x] + 1;
          parent[y] = x;
          queue.push(y);
        }
      }
    };
    const unitsWhere = (pred: (id: string) => boolean) =>
      [...new Set(b.infra.filter((n) => pred(n.id)).map((n) => unitOf[n.id]))];
    // Wurzeln nach Rang: Firewall/Router → Core → Distribution (MS425/N9K ohne Core-Namen)
    // → sonst die Unit mit den meisten Nachbar-Units. Rangniedrigere Backbone-Switches
    // werden per BFS als Kinder erreicht (Nexus oben, Meraki-Core darunter).
    const fwRoots = unitsWhere((id) => nodeType[id] === "firewall" || nodeType[id] === "router");
    const coreRoots = unitsWhere((id) => coreIds.has(id));
    const distRoots = unitsWhere((id) => distIds.has(id));
    let roots = fwRoots.length ? fwRoots : coreRoots.length ? coreRoots : distRoots;
    if (!roots.length) {
      const cand = units.map((_, u) => u).filter((u) => nodeType[units[u][0]] === "switch" && unitDegree(u) > 0);
      const max = Math.max(0, ...cand.map(unitDegree));
      roots = cand.filter((u) => unitDegree(u) === max);
    }
    // Direkt verbundene Wurzeln (vPC-/MLAG-Paar wie die beiden Nexus) als EINE Einheit
    // nebeneinander zeichnen, statt den Baum zwischen zwei entfernten Wurzeln aufzuteilen.
    for (const a of roots.slice()) {
      for (const bb of roots.slice()) {
        if (a === bb || !units[a].length || !units[bb].length || !unitAdj[a].has(bb)) continue;
        units[a] = [...units[a], ...units[bb]].sort(byLbl);
        for (const m of units[bb]) unitOf[m] = a;
        units[bb] = [];
        for (const v of unitAdj[bb]) {
          unitAdj[v].delete(bb);
          if (v !== a) {
            unitAdj[v].add(a);
            unitAdj[a].add(v);
          }
        }
        unitAdj[a].delete(a);
        unitAdj[bb] = new Set();
      }
    }
    roots = [...new Set(roots.filter((r) => units[r].length))];
    visit(roots.sort((p, q) => unitLabel(p).localeCompare(unitLabel(q))));
    const mainRoots = roots.filter((r) => parent[r] === null);
    // Zweiter Baum: Waisen unter „Unbekannter Switch"
    const unknownRoots = unitsWhere((id) => nodeType[id] === "unknown" && depth[unitOf[id]] === undefined);
    visit(unknownRoots);
    const looseUnits = units.map((_, u) => u).filter((u) => units[u].length && depth[u] === undefined);
    for (const u of looseUnits) {
      depth[u] = 0;
      parent[u] = null;
    }
    for (const u of units.keys()) {
      const p = parent[u];
      if (p !== null && p !== undefined) (children[p] ??= []).push(u);
    }
    for (const p of Object.keys(children))
      children[Number(p)].sort((x, y) => unitLabel(x).localeCompare(unitLabel(y)));

    // Teilbaum-Breiten (Unit-Reihe + AP-Grids vs. Summe der Kinder), dann rekursiv platzieren.
    const unitW = (u: number) =>
      units[u].reduce((s, m) => s + groupW(m), 0) + (units[u].length - 1) * STACK_GAP;
    const subW: Record<number, number> = {};
    const measure = (u: number): number => {
      const kids = children[u] ?? [];
      const kidsW = kids.reduce((s, k) => s + measure(k), 0) + Math.max(0, kids.length - 1) * GROUP_GAP;
      return (subW[u] = Math.max(unitW(u), kidsW));
    };
    const rowH: Record<number, number> = {};
    const levelOf: Record<string, number> = {};
    const apRowOf: Record<string, number> = {};
    const place = (u: number, x0: number, levelBase: number) => {
      const d = levelBase + (depth[u] ?? 0);
      const kids = children[u] ?? [];
      const kidsW = kids.reduce((s, k) => s + subW[k], 0) + Math.max(0, kids.length - 1) * GROUP_GAP;
      let cx = x0 + (subW[u] - kidsW) / 2;
      for (const k of kids) {
        place(k, cx, levelBase);
        cx += subW[k] + GROUP_GAP;
      }
      let gx = x0 + (subW[u] - unitW(u)) / 2;
      for (const m of units[u]) {
        rowH[d] = Math.max(rowH[d] ?? 0, groupH(m));
        const cols = apCols(m);
        local[m] = { x: gx + groupW(m) / 2 - AP_DX / 2, y: 0 };
        levelOf[m] = d;
        (b.apsBySwitch[m] ?? []).slice().sort(byLabel).forEach((ap, i) => {
          local[ap.id] = { x: gx + (i % cols) * AP_DX, y: 0 };
          levelOf[ap.id] = d;
          apRowOf[ap.id] = Math.floor(i / cols);
        });
        gx += groupW(m) + STACK_GAP;
      }
    };
    const forest = (rootUnits: number[], levelBase: number): number => {
      let x = 0;
      for (const r of rootUnits) {
        measure(r);
        place(r, x, levelBase);
        x += subW[r] + GROUP_GAP;
      }
      return Math.max(0, x - GROUP_GAP);
    };
    const maxDepth = (rootUnits: number[]) => {
      let m = 0;
      const walk = (u: number) => {
        m = Math.max(m, depth[u]);
        for (const k of children[u] ?? []) walk(k);
      };
      rootUnits.forEach(walk);
      return m;
    };
    const widths: number[] = [];
    const bands: { roots: number[] }[] = [];
    let level = 0;
    for (const rootUnits of [mainRoots, unknownRoots, looseUnits]) {
      if (!rootUnits.length) continue;
      bands.push({ roots: rootUnits });
      widths.push(forest(rootUnits, level));
      level += maxDepth(rootUnits) + 1;
    }
    // Ebenen → Pixel: jede Ebene so hoch wie ihr höchster Switch+AP-Block (+ Reihenabstand).
    const levelY: Record<number, number> = {};
    let y = 0;
    for (let l = 0; l < level; l++) {
      levelY[l] = y;
      y += (rowH[l] ?? SW_H) + ROW_GAP;
    }
    for (const id of Object.keys(local)) {
      const apRow = apRowOf[id];
      local[id].y = levelY[levelOf[id]] + (apRow !== undefined ? SW_H + apRow * AP_DY : 0);
    }
    // Bänder horizontal auf gemeinsamer Mittelachse zentrieren → Baum-Optik
    const siteW = Math.max(1, ...widths);
    bands.forEach((band, i) => {
      const off = (siteW - widths[i]) / 2;
      const shift = (u: number) => {
        for (const m of units[u]) {
          local[m].x += off;
          for (const ap of b.apsBySwitch[m] ?? []) local[ap.id].x += off;
        }
        for (const k of children[u] ?? []) shift(k);
      };
      band.roots.forEach(shift);
    });
    // Lose APs (ohne Switch) als Grid unten
    const loose = b.loose.slice().sort(byLabel);
    if (loose.length) {
      const cols = Math.min(8, loose.length);
      const w = Math.min(cols, loose.length) * AP_DX;
      const off = (siteW - w) / 2;
      loose.forEach((n, i) => {
        local[n.id] = { x: off + (i % cols) * AP_DX, y: y + Math.floor(i / cols) * AP_DY };
      });
      y += Math.ceil(loose.length / cols) * AP_DY;
    }
    return { local, w: siteW, h: y };
  }

  type Box = { local: Record<string, XY>; w: number; h: number; count: number };
  const ids = [...siteOrder, ...Object.keys(buckets).filter((k) => !siteOrder.includes(k))];
  const boxes: Box[] = [];
  for (const id of ids) {
    const b = buckets[id];
    if (!b) continue;
    const placed = new Set(b.infra.map((s) => s.id));
    for (const swId of Object.keys(b.apsBySwitch))
      if (!placed.has(swId)) {
        b.loose.push(...b.apsBySwitch[swId]);
        delete b.apsBySwitch[swId];
      }
    const count = b.infra.length + Object.values(b.apsBySwitch).flat().length + b.loose.length;
    if (!count) continue;
    const { local, w, h } = layoutSite(b);
    boxes.push({ local, w, h, count });
  }
  if (!boxes.length) return {};

  // Phase 2: vertikaler Stapel — größter Standort oben, alle horizontal auf gemeinsamer
  // Mittelachse zentriert; darunter die kleineren in absteigender Größe.
  boxes.sort((a, c) => c.count - a.count);
  const totalW = Math.max(...boxes.map((b) => b.w));
  const pos: Record<string, XY> = {};
  let y = 0;
  for (const box of boxes) {
    const ox = (totalW - box.w) / 2;
    for (const [k, p] of Object.entries(box.local)) pos[k] = { x: ox + p.x, y: y + p.y };
    y += box.h + SITE_GAP;
  }
  return pos;
}

const POS_KEY = "netbuddy-topo-positions-v4"; // v4 = Baum-Layout

export function clearSavedPositions() {
  localStorage.removeItem(POS_KEY);
}

function loadPositions(): Record<string, { x: number; y: number }> {
  try {
    return JSON.parse(localStorage.getItem(POS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function savePositions(cy: cytoscape.Core) {
  const pos: Record<string, { x: number; y: number }> = loadPositions();
  cy.nodes(":childless").forEach((n) => {
    if (!n.data("ephemeral")) pos[n.id()] = { ...n.position() };
  });
  localStorage.setItem(POS_KEY, JSON.stringify(pos));
}

/** Zoom-/pan-barer Cytoscape-Graph; Standorte sind Container (Compound-Knoten). */
export function TopologyGraph({
  topology,
  visibleNodeTypes,
  visibleEdgeTypes,
  theme,
  fontSize,
  edgeWidth,
  edgeColor,
  endpoints,
  layoutNonce,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  // Graph einmal aufbauen.
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...topology.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.label,
            ntype: n.type,
            ...(n.parent ? { parent: n.parent } : {}),
          },
        })),
        ...topology.edges.map((e) => ({
          data: {
            id: `${e.source}->${e.target}:${e.type}`,
            source: e.source,
            target: e.target,
            etype: e.type,
            elabel: e.label ?? "",
            up: e.up !== false, // null/true → up-Optik
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            "background-color": NODE_COLOR.other,
            label: "data(label)",
            color: labelColor(theme),
            "font-size": fontSize,
            "text-valign": "bottom",
            "text-margin-y": 6,
            shape: "round-rectangle",
            width: 44,
            height: 40,
          },
        },
        ...Object.entries(NODE_COLOR).map(([ntype, color]) => ({
          selector: `node[ntype = "${ntype}"]`,
          style: { "background-color": color },
        })),
        // Standort = Container („Wolke"): halbtransparent, gestrichelt, Label oben links.
        {
          selector: "node:parent",
          style: {
            shape: "round-rectangle",
            "background-color": NODE_COLOR.site,
            "background-opacity": 0.08,
            "border-width": 2,
            "border-style": "dashed",
            "border-color": NODE_COLOR.site,
            label: "data(label)",
            "text-valign": "top",
            "text-halign": "center",
            "text-margin-y": -6,
            "font-weight": "bold",
            padding: "24px",
          },
        },
        { selector: 'node[ntype = "endpoint"]', style: { shape: "diamond", width: 30, height: 30 } },
        // Icon als Hintergrundbild: die SVGs bringen Maße + Innenabstand mit → "contain"
        // skaliert sauber ohne Beschnitt. Leere Standorte (childless) bekommen den Pin.
        ...Object.entries(NODE_ICON).map(([ntype, uri]) => ({
          selector: `node[ntype = "${ntype}"]:childless`,
          style: {
            "background-image": uri,
            "background-fit": "contain" as const,
          },
        })),
        // Container (Standorte mit Inhalt) tragen kein Icon — nur Rahmen + Label.
        { selector: "node:parent", style: { "background-image": "none" } },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#cbd5e1",
            "curve-style": "bezier",
            "target-arrow-shape": "none",
          },
        },
        { selector: 'edge[etype = "lldp"]', style: { "line-color": "#94a3b8", "line-style": "dashed" } },
        // Stack-Member: kurze, kräftige Klammer auf gleicher Ebene (ein logischer Switch)
        {
          selector: 'edge[etype = "stack"]',
          style: { width: 4, "line-color": "#2563eb", "line-style": "solid", "curve-style": "straight" },
        },
        // AP→Switch-Uplink: dünne, durchgezogene Linie, Port-Label klein.
        {
          selector: 'edge[etype = "uplink"]',
          style: {
            width: 1.5,
            "line-color": "#64748b",
            "line-style": "solid",
            label: "data(elabel)",
            "font-size": 7,
            color: labelColor(theme),
          },
        },
        // Inferierte Hierarchie-Kante (FW→Core, Core→Access; nicht per LLDP gemessen): gestrichelt.
        {
          selector: 'edge[etype = "inferred"]',
          style: { width: 1.5, "line-color": "#475569", "line-style": "dashed" },
        },
        // Mesh: drahtlose AP→AP-Verbindung, gestrichelt + Label "Mesh".
        {
          selector: 'edge[etype = "wireless"]',
          style: {
            width: 2,
            "line-color": "#0ea5e9",
            "line-style": "dashed",
            "curve-style": "bezier",
            label: "data(elabel)",
            "font-size": 8,
            color: labelColor(theme),
            "text-background-color": theme === "dark" ? "#0f172a" : "#f8fafc",
            "text-background-opacity": 0.8,
          },
        },
        // VPN: kräftige Kante zwischen Standorten, Label = Tunnelname, rot wenn down.
        {
          selector: 'edge[etype = "vpn"]',
          style: {
            width: 3,
            "line-color": "#16a34a",
            "line-style": "solid",
            label: "data(elabel)",
            "font-size": 9,
            color: labelColor(theme),
            "text-background-color": theme === "dark" ? "#0f172a" : "#f8fafc",
            "text-background-opacity": 0.8,
          },
        },
        { selector: 'edge[etype = "vpn"][!up]', style: { "line-color": "#dc2626", "line-style": "dotted" } },
        {
          selector: 'edge[etype = "endpoint"]',
          style: { "line-color": "#f59e0b", label: "data(elabel)", "font-size": 9, color: labelColor(theme) },
        },
        // Such-Hervorhebung: Treffer + Pfad leuchten, der Rest wird gedimmt.
        { selector: ".dim", style: { opacity: 0.18 } },
        {
          selector: "node.found",
          style: {
            "border-width": 4,
            "border-color": "#f59e0b",
            "border-opacity": 1,
            "z-index": 9999,
            "font-weight": "bold",
          },
        },
        {
          selector: "edge.found-edge",
          style: {
            "line-color": "#f59e0b",
            "line-style": "solid",
            width: 3.5,
            "z-index": 9999,
            label: "data(elabel)",
            "font-size": 10,
            "font-weight": "bold",
            color: labelColor(theme),
            "text-background-color": theme === "dark" ? "#0f172a" : "#f8fafc",
            "text-background-opacity": 0.85,
          },
        },
      ],
      layout: { name: "preset" },
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    // Stabiles Layout: gespeicherte Positionen anwenden; nur unbekannte Knoten bekommen
    // eine deterministische Seed-Position. cose läuft NUR, wenn neue Knoten dazukamen
    // (randomize:false → verfeinert reproduzierbar ab den gesetzten Positionen).
    // Strukturiertes Layout als Basis; vom Nutzer verschobene Knoten (gespeichert) gewinnen.
    const saved = loadPositions();
    const structured = computeStructuredPositions(topology);
    cy.nodes(":childless").forEach((n) => {
      const p = saved[n.id()] ?? structured[n.id()];
      if (p) n.position(p);
    });
    cy.fit(undefined, 60); // dynamischer Zoom: passt sich der Gerätemenge an
    cy.on("dragfree", "node", () => savePositions(cy));
    // Doppelklick auf den Hintergrund = Ansicht wieder einpassen (bei vielen Geräten).
    cy.on("dbltap", (evt) => {
      if (evt.target === cy) cy.fit(undefined, 60);
    });

    return () => cy.destroy();
  }, [topology, layoutNonce]);

  // Layer-Sichtbarkeit anwenden (Site-Container bleiben immer sichtbar — sie tragen die Geräte).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().forEach((n) => {
      if (n.isParent() || n.data("ntype") === "site") return;
      const show = n.data("ephemeral") || visibleNodeTypes.has(n.data("ntype"));
      n.style("display", show ? "element" : "none");
    });
    cy.edges().forEach((e) => {
      const show = e.data("ephemeral") || visibleEdgeTypes.has(e.data("etype"));
      e.style("display", show ? "element" : "none");
    });
  }, [visibleNodeTypes, visibleEdgeTypes]);

  // Such-Treffer hervorheben: gefundenes Gerät IM Graph markieren + Uplink-Pfad/Port betonen,
  // Rest dimmen. Endgeräte, die KEIN Graph-Knoten sind (Clients), als ephemerer Knoten am Switch.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements("[?ephemeral]").remove();
    cy.elements().removeClass("found found-edge dim");
    if (!endpoints.length) return;

    let matched = cy.collection();
    const floating: EndpointHighlight[] = [];
    for (const e of endpoints) {
      const needle = (e.label || "").trim().toLowerCase();
      let node = cy
        .nodes()
        .filter((n) => !n.isParent() && (n.data("label") || "").toLowerCase() === needle);
      if (node.empty() && needle.length > 2)
        node = cy
          .nodes()
          .filter((n) => !n.isParent() && (n.data("label") || "").toLowerCase().includes(needle));
      if (node.nonempty()) matched = matched.union(node);
      else floating.push(e);
    }

    // Clients (kein Graph-Knoten) → ephemerer Knoten am Switch, mit Port als Kantenlabel.
    for (const e of floating) {
      const target = cy.getElementById(`device:${e.deviceId}`);
      if (target.empty()) continue;
      const pos = target.position();
      cy.add({
        group: "nodes",
        data: { id: e.id, label: e.label, ntype: "endpoint", ephemeral: true },
        position: { x: pos.x + 70, y: pos.y + 70 },
      });
      cy.add({
        group: "edges",
        data: {
          id: `${e.id}->edge`,
          source: e.id,
          target: `device:${e.deviceId}`,
          etype: "endpoint",
          ephemeral: true,
          elabel: e.port,
        },
      });
    }
    const ephem = cy.elements("[?ephemeral]");

    // Pfad: Uplink-/LLDP-Kanten des Treffers + deren Gegenknoten (Switch). Kanten sichtbar machen.
    const pathEdges = matched.connectedEdges('[etype = "uplink"], [etype = "lldp"], [etype = "wireless"]');
    pathEdges.style("display", "element");
    const pathNodes = matched.union(pathEdges.connectedNodes());
    const focus = pathNodes.union(pathEdges).union(ephem);

    if (matched.nonempty() || ephem.nonempty()) {
      cy.elements().not(focus).not("node:parent").addClass("dim");
      matched.addClass("found");
      pathNodes.difference(matched).addClass("found");
      pathEdges.addClass("found-edge");
    }
    if (focus.nonempty())
      cy.animate({ fit: { eles: focus.closedNeighborhood(), padding: 90 }, duration: 300 });
  }, [endpoints]);

  // Label-Farbe an das Theme anpassen (Canvas-Render, daher nicht über CSS steuerbar).
  useEffect(() => {
    cyRef.current?.nodes().style("color", labelColor(theme));
  }, [theme]);

  // Anzeige-Einstellungen (Schriftgröße, Linien-Breite/-Farbe) live anwenden.
  useEffect(() => {
    cyRef.current?.nodes().style("font-size", fontSize);
  }, [fontSize]);
  useEffect(() => {
    cyRef.current?.edges('[etype = "lldp"]').style({ width: edgeWidth, "line-color": edgeColor });
  }, [edgeWidth, edgeColor]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}

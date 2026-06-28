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

function computeStructuredPositions(topo: Topology): Record<string, XY> {
  const AP_DX = 64,
    AP_DY = 64,
    SW_H = 72,
    GROUP_GAP = 44,
    ROW_GAP = 72,
    BB_DX = 150,
    BACKBONE_H = 104,
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

  // Core-Switch-Erkennung: Ziel inferierter/Uplink-Switch-Kanten, FW-Nachbar (LLDP) oder Name.
  const fwIds = new Set(
    topo.nodes.filter((n) => n.type === "firewall" || n.type === "router").map((n) => n.id),
  );
  const coreIds = new Set<string>();
  for (const e of topo.edges) {
    if (e.type === "lldp") {
      if (fwIds.has(e.source) && nodeType[e.target] === "switch") coreIds.add(e.target);
      if (fwIds.has(e.target) && nodeType[e.source] === "switch") coreIds.add(e.source);
    } else if (e.type === "inferred" && nodeType[e.target] === "switch") {
      coreIds.add(e.target); // FW→Core bzw. Access→Core: Ziel ist der Core
    } else if (
      e.type === "uplink" &&
      nodeType[e.source] === "switch" &&
      nodeType[e.target] === "switch"
    ) {
      coreIds.add(e.target);
    }
  }
  for (const n of topo.nodes)
    if (n.type === "switch" && (n.label || "").toLowerCase().includes("core")) coreIds.add(n.id);

  type N = (typeof topo.nodes)[number];
  type Bucket = { backbone: N[]; switches: N[]; apsBySwitch: Record<string, N[]>; loose: N[] };
  const buckets: Record<string, Bucket> = {};
  const bucket = (id: string) =>
    (buckets[id] ??= { backbone: [], switches: [], apsBySwitch: {}, loose: [] });
  const siteOrder = topo.nodes.filter((n) => n.type === "site").map((n) => n.id);

  for (const n of topo.nodes) {
    if (n.type === "site") continue;
    const b = bucket(n.parent ?? "site:none");
    if (n.type === "firewall" || n.type === "router") b.backbone.push(n);
    else if (n.type === "switch" || n.type === "unknown") b.switches.push(n);
    else if (n.type === "ap" && switchOfAp[n.id]) (b.apsBySwitch[switchOfAp[n.id]] ??= []).push(n);
    else b.loose.push(n);
  }

  const byLabel = (a: { label: string }, c: { label: string }) => a.label.localeCompare(c.label);

  // Phase 1: Layout EINES Standorts als Hierarchie von oben nach unten:
  // Firewall/Router → Core-Switch(es) → Access-Switches (je mit AP-Grid darunter) → Loose.
  function layoutSite(b: Bucket): { local: Record<string, XY>; w: number; h: number } {
    const local: Record<string, XY> = {};
    type Row = { ids: string[]; width: number };
    const rows: Row[] = [];
    let y = 0;

    // platziert eine Reihe von Switch-Gruppen (Switch + AP-Grid darunter) ab atY, links bündig
    const placeGroups = (switches: N[], atY: number): { width: number; height: number; ids: string[] } => {
      let gx = 0,
        maxH = 0;
      const ids: string[] = [];
      for (const sw of switches) {
        const aps = (b.apsBySwitch[sw.id] ?? []).slice().sort(byLabel);
        const cols = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(aps.length || 1))));
        const groupW = Math.max(AP_DX, cols * AP_DX);
        local[sw.id] = { x: gx + groupW / 2 - AP_DX / 2, y: atY };
        ids.push(sw.id);
        aps.forEach((ap, i) => {
          local[ap.id] = {
            x: gx + (i % cols) * AP_DX,
            y: atY + SW_H + Math.floor(i / cols) * AP_DY,
          };
          ids.push(ap.id);
        });
        maxH = Math.max(maxH, SW_H + Math.ceil((aps.length || 1) / cols) * AP_DY);
        gx += groupW + GROUP_GAP;
      }
      return { width: Math.max(0, gx - GROUP_GAP), height: maxH, ids };
    };

    // Band: Backbone (Firewall/Router)
    if (b.backbone.length) {
      const ids: string[] = [];
      b.backbone.sort(byLabel).forEach((n, i) => {
        local[n.id] = { x: i * BB_DX, y };
        ids.push(n.id);
      });
      rows.push({ ids, width: (b.backbone.length - 1) * BB_DX + AP_DX });
      y += BACKBONE_H;
    }

    const cores = b.switches.filter((s) => coreIds.has(s.id)).sort(byLabel);
    const access = b.switches.filter((s) => !coreIds.has(s.id)).sort(byLabel);

    if (cores.length) {
      const r = placeGroups(cores, y);
      rows.push({ ids: r.ids, width: r.width });
      y += r.height + ROW_GAP;
    }
    const maxGroups = Math.min(6, Math.max(2, Math.ceil(Math.sqrt(access.length || 1))));
    for (let i = 0; i < access.length; i += maxGroups) {
      const r = placeGroups(access.slice(i, i + maxGroups), y);
      rows.push({ ids: r.ids, width: r.width });
      y += r.height + ROW_GAP;
    }

    const loose = b.loose.slice().sort(byLabel);
    if (loose.length) {
      const cols = Math.min(8, loose.length);
      const ids: string[] = [];
      loose.forEach((n, i) => {
        local[n.id] = { x: (i % cols) * AP_DX, y: y + Math.floor(i / cols) * AP_DY };
        ids.push(n.id);
      });
      rows.push({ ids, width: Math.min(cols, loose.length) * AP_DX });
      y += Math.ceil(loose.length / cols) * AP_DY;
    }

    // jede Reihe horizontal auf gemeinsamer Mittelachse zentrieren → Baum-Optik
    const siteW = Math.max(1, ...rows.map((r) => r.width));
    for (const r of rows) {
      const off = (siteW - r.width) / 2;
      for (const id of r.ids) local[id].x += off;
    }
    return { local, w: siteW, h: y };
  }

  type Box = { local: Record<string, XY>; w: number; h: number; count: number };
  const ids = [...siteOrder, ...Object.keys(buckets).filter((k) => !siteOrder.includes(k))];
  const boxes: Box[] = [];
  for (const id of ids) {
    const b = buckets[id];
    if (!b) continue;
    const placed = new Set(b.switches.map((s) => s.id));
    for (const swId of Object.keys(b.apsBySwitch))
      if (!placed.has(swId)) b.loose.push(...b.apsBySwitch[swId]);
    const count =
      b.backbone.length +
      b.switches.length +
      Object.values(b.apsBySwitch).flat().length +
      b.loose.length;
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

const POS_KEY = "netbuddy-topo-positions-v3";

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

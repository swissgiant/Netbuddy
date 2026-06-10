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
}

const labelColor = (theme: "dark" | "light") => (theme === "dark" ? "#e2e8f0" : "#0f172a");

// Deterministische Startposition je Knoten-ID: gleiche Daten → gleiches Layout (statt
// Zufall bei jedem F5). cose verfeinert von dort aus reproduzierbar.
function seededPosition(id: string): { x: number; y: number } {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const a = (h >>> 0) / 4294967295;
  const b = ((Math.imul(h, 2654435761) >>> 0)) / 4294967295;
  return { x: 200 + a * 700, y: 100 + b * 500 };
}

const POS_KEY = "netbuddy-topo-positions";

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
      ],
      layout: { name: "preset" },
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;

    // Stabiles Layout: gespeicherte Positionen anwenden; nur unbekannte Knoten bekommen
    // eine deterministische Seed-Position. cose läuft NUR, wenn neue Knoten dazukamen
    // (randomize:false → verfeinert reproduzierbar ab den gesetzten Positionen).
    const saved = loadPositions();
    let hasNew = false;
    cy.nodes(":childless").forEach((n) => {
      const p = saved[n.id()];
      if (p) {
        n.position(p);
      } else {
        n.position(seededPosition(n.id()));
        hasNew = true;
      }
    });
    if (hasNew) {
      const layout = cy.layout({ name: "cose", animate: false, randomize: false } as never);
      layout.on("layoutstop", () => {
        savePositions(cy);
        cy.fit(undefined, 60); // dynamischer Zoom: passt sich der Gerätemenge an
      });
      layout.run();
    } else {
      cy.fit(undefined, 60);
    }
    cy.on("dragfree", "node", () => savePositions(cy));
    // Doppelklick auf den Hintergrund = Ansicht wieder einpassen (bei vielen Geräten).
    cy.on("dbltap", (evt) => {
      if (evt.target === cy) cy.fit(undefined, 60);
    });

    return () => cy.destroy();
  }, [topology]);

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

  // Such-Treffer als ephemere Endgerät-Knoten am jeweiligen Switch einblenden (sonst nicht).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements("[?ephemeral]").remove();
    const ids: string[] = [];
    for (const e of endpoints) {
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
      ids.push(e.id);
    }
    if (ids.length) {
      const nodes = cy.nodes("[?ephemeral]");
      cy.animate({ fit: { eles: nodes.closedNeighborhood(), padding: 80 }, duration: 300 });
    }
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

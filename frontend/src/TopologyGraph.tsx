import cytoscape from "cytoscape";
import { useEffect, useRef } from "react";
import type { Topology } from "./api";

// Farbe je Knoten-Typ.
const NODE_COLOR: Record<string, string> = {
  site: "#6b7280",
  switch: "#2563eb",
  firewall: "#dc2626",
  router: "#7c3aed",
  ap: "#059669",
  other: "#9ca3af",
};

interface Props {
  topology: Topology;
  // sichtbare Layer (Knoten-Typen + Kanten-Typen), vom Parent gesteuert
  visibleNodeTypes: Set<string>;
  visibleEdgeTypes: Set<string>;
  theme: "dark" | "light";
  fontSize: number;
  edgeWidth: number;
  edgeColor: string;
}

const labelColor = (theme: "dark" | "light") => (theme === "dark" ? "#e2e8f0" : "#0f172a");

/** Zoom-/pan-barer Cytoscape-Graph; Layer werden per Sichtbarkeit gefiltert. */
export function TopologyGraph({
  topology,
  visibleNodeTypes,
  visibleEdgeTypes,
  theme,
  fontSize,
  edgeWidth,
  edgeColor,
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
          data: { id: n.id, label: n.label, ntype: n.type },
        })),
        ...topology.edges.map((e) => ({
          data: { id: `${e.source}->${e.target}:${e.type}`, source: e.source, target: e.target, etype: e.type },
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
            "text-margin-y": 4,
            width: 26,
            height: 26,
          },
        },
        // Farbe je Knoten-Typ via Selektoren (typsicher, ohne Funktions-Mapper).
        ...Object.entries(NODE_COLOR).map(([ntype, color]) => ({
          selector: `node[ntype = "${ntype}"]`,
          style: { "background-color": color },
        })),
        { selector: 'node[ntype = "site"]', style: { shape: "round-rectangle", width: 40, height: 28 } },
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
      ],
      layout: { name: "cose", animate: false },
      wheelSensitivity: 0.2,
    });
    cyRef.current = cy;
    return () => cy.destroy();
  }, [topology]);

  // Layer-Sichtbarkeit anwenden.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().forEach((n) => {
      n.style("display", visibleNodeTypes.has(n.data("ntype")) ? "element" : "none");
    });
    cy.edges().forEach((e) => {
      e.style("display", visibleEdgeTypes.has(e.data("etype")) ? "element" : "none");
    });
  }, [visibleNodeTypes, visibleEdgeTypes]);

  // Label-Farbe an das Theme anpassen (Canvas-Render, daher nicht über CSS steuerbar).
  useEffect(() => {
    cyRef.current?.nodes().style("color", labelColor(theme));
  }, [theme]);

  // Anzeige-Einstellungen (Schriftgröße, Linien-Breite/-Farbe) live anwenden.
  useEffect(() => {
    cyRef.current?.nodes().style("font-size", fontSize);
  }, [fontSize]);
  useEffect(() => {
    cyRef.current?.edges().style({ width: edgeWidth, "line-color": edgeColor });
  }, [edgeWidth, edgeColor]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}

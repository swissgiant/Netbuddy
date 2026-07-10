import { describe, expect, it } from "vitest";
import type { SurveyDataIn } from "../vlanTopoElements";
import { buildVlanTopoElements } from "../vlanTopoElements";
import fixture from "./fixtures/survey.json";

// Das Fixture ist ein ECHTER Prod-Survey-Lauf (9 Standorte inkl. Meraki, 38-VLAN-Site).
const data = fixture as unknown as SurveyDataIn;

function split(elements: ReturnType<typeof buildVlanTopoElements>) {
  const nodes = elements.filter((e) => !("source" in e.data));
  const edges = elements.filter((e) => "source" in e.data);
  return { nodes, edges };
}

describe("buildVlanTopoElements (echtes Prod-Fixture)", () => {
  const elements = buildVlanTopoElements(data);
  const { nodes, edges } = split(elements);
  const nodeIds = new Set(nodes.map((n) => String(n.data.id)));

  it("erzeugt pro Site einen Container und pro VLAN einen Knoten", () => {
    const siteCount = Object.keys(data.sites).length;
    const vlanCount = Object.values(data.sites).reduce((a, v) => a + v.length, 0);
    expect(nodes.filter((n) => n.data.kind === "site")).toHaveLength(siteCount);
    expect(nodes.filter((n) => n.data.kind === "vlan")).toHaveLength(vlanCount);
    expect(siteCount).toBeGreaterThanOrEqual(9); // inkl. Meraki-Standorte
    expect(vlanCount).toBeGreaterThan(100);
  });

  it("alle IDs sind eindeutig", () => {
    const ids = elements.map((e) => String(e.data.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("jede Kante referenziert existierende Knoten", () => {
    for (const e of edges) {
      expect(nodeIds.has(String(e.data.source))).toBe(true);
      expect(nodeIds.has(String(e.data.target))).toBe(true);
    }
  });

  it("alle Kind-Knoten haben Positionen, keine zwei am selben Punkt", () => {
    const positioned = nodes.filter((n) => n.data.kind !== "site");
    const seen = new Set<string>();
    for (const n of positioned) {
      expect(n.position).toBeDefined();
      const key = `${n.position!.x},${n.position!.y}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  });

  it("Testnetz-Mesh: VPN-Kanten existieren und nur zwischen gleicher VLAN-ID", () => {
    const vpn = edges.filter((e) => e.data.ekind === "vpn");
    expect(vpn.length).toBeGreaterThan(0);
    for (const e of vpn) {
      const vidSrc = String(e.data.source).split(":").pop();
      const vidDst = String(e.data.target).split(":").pop();
      expect(vidSrc).toBe(vidDst);
    }
  });

  it("Aufsetz-/Gästenetz haben Internet-Kanten, aber keine LAN-Kanten", () => {
    const bySrcVid = (vid: number, kind: string) =>
      edges.filter(
        (e) => e.data.ekind === kind && String(e.data.source).endsWith(`:${vid}`),
      ).length;
    expect(bySrcVid(120, "inet")).toBeGreaterThan(0);
    expect(bySrcVid(130, "inet")).toBeGreaterThan(0);
    expect(bySrcVid(120, "lan")).toBe(0);
    expect(bySrcVid(130, "lan")).toBe(0);
  });
});

describe("buildVlanTopoElements (Randfälle)", () => {
  it("leerer Survey → keine Elemente", () => {
    expect(buildVlanTopoElements({ sites: {} })).toHaveLength(0);
  });

  it("VPN-Kante nur, wenn BEIDE Sites das VLAN über Tunnel erlauben", () => {
    const mini: SurveyDataIn = {
      sites: {
        A: [{ vlan_id: 10, names: [], gateways: [], dhcp_servers: [], dhcp_helpers: [], carriers: [], access_ports: 0 }],
        B: [{ vlan_id: 10, names: [], gateways: [], dhcp_servers: [], dhcp_helpers: [], carriers: [], access_ports: 0 }],
      },
      transitions: {
        A: [{ vlan_id: 10, to: "vpn", detail: "t1", policy: null, device: "FW-A" }],
        // B erlaubt NICHT → keine Kante
      },
    };
    const edges = buildVlanTopoElements(mini).filter((e) => "source" in e.data);
    expect(edges.filter((e) => e.data.ekind === "vpn")).toHaveLength(0);
  });
});

import { describe, expect, it } from "vitest";
import type { Topology } from "../api";
import { computeStructuredPositions } from "../TopologyGraph";

/** Riese-artiger Standort: Nexus-Core → Meraki-Core → Access-Stack (2 Member) → AP; plus Waise. */
function site(): Topology {
  const S = "site:s00";
  const n = (id: string, type: Topology["nodes"][number]["type"], extra: Partial<Topology["nodes"][number]> = {}) => ({
    id: `device:${id}`,
    label: id,
    type,
    parent: S,
    ...extra,
  });
  return {
    nodes: [
      { id: S, label: "S00", type: "site", parent: null },
      n("ncs101", "switch", { role: "core" }),
      n("nsw100", "switch"),
      n("nsw110", "switch", { stack: "Uff. IT" }),
      n("nsw111", "switch", { stack: "Uff. IT" }),
      n("nsw112", "switch"),
      n("nap100", "ap"),
      n("nap101", "ap"),
      { id: "unknown:s00", label: "Unbekannter Switch", type: "unknown", parent: S },
      n("tvcc01", "switch"),
    ],
    edges: [
      { source: "device:nsw100", target: "device:ncs101", type: "lldp" },
      { source: "device:nsw110", target: "device:nsw100", type: "lldp" },
      { source: "device:nsw110", target: "device:nsw111", type: "stack" },
      { source: "device:nsw112", target: "device:nsw111", type: "lldp" },
      { source: "device:nap100", target: "device:nsw112", type: "uplink" },
      { source: "device:nap101", target: "device:nsw112", type: "uplink" },
      { source: "device:tvcc01", target: "unknown:s00", type: "uplink" },
    ],
  };
}

describe("computeStructuredPositions (Baum-Layout)", () => {
  const pos = computeStructuredPositions(site());
  const y = (id: string) => pos[id].y;
  const x = (id: string) => pos[id].x;

  it("ordnet von oben nach unten: Core → Meraki-Core → Access → AP", () => {
    expect(y("device:ncs101")).toBeLessThan(y("device:nsw100"));
    expect(y("device:nsw100")).toBeLessThan(y("device:nsw110"));
    expect(y("device:nsw110")).toBeLessThan(y("device:nsw112"));
    expect(y("device:nsw112")).toBeLessThan(y("device:nap100"));
  });

  it("legt Stack-Member auf dieselbe Ebene nebeneinander", () => {
    expect(y("device:nsw110")).toBe(y("device:nsw111"));
    expect(x("device:nsw110")).not.toBe(x("device:nsw111"));
  });

  it("hängt APs direkt unter ihren Switch und Waisen unter den Unbekannten Switch", () => {
    expect(Math.abs(x("device:nap100") - x("device:nsw112"))).toBeLessThan(200);
    expect(y("unknown:s00")).toBeGreaterThan(y("device:nap100"));
    expect(y("device:tvcc01")).toBeGreaterThan(y("unknown:s00"));
  });

  it("vergibt jedem Knoten eine Position, keine zwei Switches auf demselben Punkt", () => {
    const ids = site().nodes.filter((n) => n.type !== "site").map((n) => n.id);
    for (const id of ids) expect(pos[id]).toBeDefined();
    const pts = new Set(ids.map((id) => `${pos[id].x},${pos[id].y}`));
    expect(pts.size).toBe(ids.length);
  });
});

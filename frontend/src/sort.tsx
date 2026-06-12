import { useMemo, useState, type ReactNode } from "react";

// Wert-Zugriff je Spalte: Feldname oder Accessor-Funktion (für berechnete Spalten
// wie Standort-Name oder zusammengesetzte Quellen).
export type Accessor<T> = (row: T) => unknown;

interface SortState {
  key: string;
  dir: 1 | -1;
}

function compare(va: unknown, vb: unknown): number {
  if (va == null && vb == null) return 0;
  if (va == null) return 1; // leere Werte ans Ende
  if (vb == null) return -1;
  if (typeof va === "number" && typeof vb === "number") return va - vb;
  if (typeof va === "boolean" && typeof vb === "boolean") {
    return (va ? 1 : 0) - (vb ? 1 : 0);
  }
  // numeric:true sortiert auch IPs/Interface-Namen sinnvoll (10.0.0.5 < 10.0.0.48, Gi1/0/2 < Gi1/0/10)
  return String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: "base" });
}

/** Klick-Sortierung für Tabellen: 1. Klick aufsteigend, 2. absteigend, 3. wieder Original. */
export function useSort<T>(rows: T[], accessors: Record<string, Accessor<T>> = {}) {
  const [sort, setSort] = useState<SortState | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const get = accessors[sort.key] ?? ((r: T) => (r as Record<string, unknown>)[sort.key]);
    return [...rows].sort((a, b) => compare(get(a), get(b)) * sort.dir);
    // accessors sind statisch je View — bewusst nicht in den Deps (sonst Re-Sort bei jedem Render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort]);

  const toggle = (key: string) =>
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: 1 };
      if (s.dir === 1) return { key, dir: -1 };
      return null; // dritter Klick: Original-Reihenfolge
    });

  return { sorted, sort, toggle };
}

export function Th({
  k,
  sort,
  onSort,
  children,
}: {
  k: string;
  sort: SortState | null;
  onSort: (key: string) => void;
  children: ReactNode;
}) {
  const active = sort?.key === k;
  return (
    <th
      onClick={() => onSort(k)}
      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
      title="Klick zum Sortieren"
    >
      {children}
      <span className="muted" style={{ fontSize: 10 }}>
        {active ? (sort!.dir === 1 ? " ▲" : " ▼") : ""}
      </span>
    </th>
  );
}

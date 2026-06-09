// Data-URI-SVG-Icons je Knoten-Typ für den Cytoscape-Graph (weißer Strich auf farbigem Knoten).
// Bewusst dieselbe Bildsprache wie die Inline-Icons in `icons.tsx`.

const svg = (body: string): string =>
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ` +
      `stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`,
  );

export const NODE_ICON: Record<string, string> = {
  switch: svg(
    '<rect x="2" y="7" width="20" height="10" rx="1.5"/>' +
      '<path d="M5 17v2M9 17v2M13 17v2M17 17v2M5 7V5M9 7V5M13 7V5M17 7V5"/>',
  ),
  firewall: svg(
    '<rect x="3" y="4" width="18" height="16" rx="1.5"/>' +
      '<path d="M3 9h18M3 15h18M9 4v5M15 9v6M9 15v5"/>',
  ),
  router: svg(
    '<rect x="2" y="13" width="20" height="7" rx="1.5"/>' +
      '<path d="M12 13V8m0 0 3 2.5M12 8 9 10.5M17 10V5m0 0 2.5 1.8M17 5l-2.5 1.8"/>',
  ),
  ap: svg('<path d="M5 12a7 7 0 0 1 14 0M8 12a4 4 0 0 1 8 0M12 14v6"/>'),
  site: svg('<path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6"/>'),
};

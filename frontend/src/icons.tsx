// Kleine Inline-SVG-Icons je Gerätetyp (skaliert, theme-neutral via currentColor).

interface IconProps {
  size?: number;
  title?: string;
}

const wrap = (size: number, title: string | undefined, children: React.ReactNode) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.6}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-label={title}
    role={title ? "img" : "presentation"}
  >
    {title && <title>{title}</title>}
    {children}
  </svg>
);

export function SwitchIcon({ size = 18, title }: IconProps) {
  // Switch: flacher Chassis-Block mit Port-Reihe.
  return wrap(size, title ?? "Switch", (
    <>
      <rect x="2" y="7" width="20" height="10" rx="1.5" />
      <path d="M5 17v2M9 17v2M13 17v2M17 17v2M5 7V5M9 7V5M13 7V5M17 7V5" />
      <circle cx="19" cy="12" r="0.9" fill="currentColor" stroke="none" />
    </>
  ));
}

export function FirewallIcon({ size = 18, title }: IconProps) {
  // Firewall: Mauerwerk-Raster (versetzte Ziegel).
  return wrap(size, title ?? "Firewall", (
    <>
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <path d="M3 9h18M3 15h18M9 4v5M15 9v6M9 15v5M15 4v0" />
    </>
  ));
}

export function RouterIcon({ size = 18, title }: IconProps) {
  return wrap(size, title ?? "Router", (
    <>
      <rect x="2" y="13" width="20" height="7" rx="1.5" />
      <path d="M6 17h.01M10 17h.01" />
      <path d="M12 13V8m0 0 3 2.5M12 8 9 10.5M17 10V5m0 0 2.5 1.8M17 5l-2.5 1.8" />
    </>
  ));
}

export function ApIcon({ size = 18, title }: IconProps) {
  // Access-Point: Funkwellen.
  return wrap(size, title ?? "Access Point", (
    <>
      <path d="M5 12a7 7 0 0 1 14 0M8 12a4 4 0 0 1 8 0" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
      <path d="M12 14v6" />
    </>
  ));
}

export function OtherIcon({ size = 18, title }: IconProps) {
  return wrap(size, title ?? "Gerät", (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M9 9h6v6H9z" />
    </>
  ));
}

export function DeviceIcon({ type, size, title }: { type: string; size?: number; title?: string }) {
  switch (type) {
    case "switch":
      return <SwitchIcon size={size} title={title} />;
    case "firewall":
      return <FirewallIcon size={size} title={title} />;
    case "router":
      return <RouterIcon size={size} title={title} />;
    case "ap":
      return <ApIcon size={size} title={title} />;
    default:
      return <OtherIcon size={size} title={title} />;
  }
}

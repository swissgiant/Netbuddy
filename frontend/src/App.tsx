import { useState } from "react";
import { applyTheme, initialTheme, type Theme } from "./theme";
import { CredentialsView } from "./views/CredentialsView";
import { DevicesView } from "./views/DevicesView";
import { TopologyView } from "./views/TopologyView";

type View = "topology" | "devices" | "credentials";

const NAV: { key: View; label: string }[] = [
  { key: "topology", label: "🌐 Topologie" },
  { key: "devices", label: "🖧 Geräte" },
  { key: "credentials", label: "🔑 Credentials" },
];

export default function App() {
  const [view, setView] = useState<View>("topology");
  const [theme, setTheme] = useState<Theme>(initialTheme());

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  };

  return (
    <div className="app">
      <nav className="nav">
        <h1>NetBuddy</h1>
        {NAV.map((n) => (
          <button
            key={n.key}
            className={`navitem ${view === n.key ? "active" : ""}`}
            onClick={() => setView(n.key)}
          >
            {n.label}
          </button>
        ))}
        {/* Userverwaltung folgt mit Phase H (Login/RBAC) */}
        <button className="navitem" disabled title="kommt mit Phase H">
          👤 Benutzer (bald)
        </button>
        <div className="spacer" />
        <button className="ghost" onClick={toggleTheme}>
          {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
        </button>
      </nav>
      <main className="main">
        {view === "topology" && <TopologyView theme={theme} />}
        {view === "devices" && <DevicesView />}
        {view === "credentials" && <CredentialsView />}
      </main>
    </div>
  );
}

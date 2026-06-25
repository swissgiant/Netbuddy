import { useEffect, useState } from "react";
import type { AuthUser } from "./api";
import { authLogout, fetchMe } from "./api";
import { applyTheme, initialTheme, type Theme } from "./theme";
import { CredentialsView } from "./views/CredentialsView";
import { DevicesView } from "./views/DevicesView";
import { DiscoveryView } from "./views/DiscoveryView";
import { LoginView } from "./views/LoginView";
import { SitesView } from "./views/SitesView";
import { SsoView } from "./views/SsoView";
import { TopologyView } from "./views/TopologyView";
import { UsersView } from "./views/UsersView";

type View = "topology" | "devices" | "discovery" | "sites" | "credentials" | "users" | "sso";

const NAV: { key: View; label: string; adminOnly?: boolean }[] = [
  { key: "topology", label: "🌐 Topologie" },
  { key: "devices", label: "🖥️ Geräte" },
  { key: "discovery", label: "🔍 Discovery" },
  { key: "sites", label: "📍 Standorte" },
  { key: "credentials", label: "🔑 Credentials" },
  { key: "users", label: "👤 Benutzer", adminOnly: true },
  { key: "sso", label: "🔐 SSO", adminOnly: true },
];

export default function App() {
  const [view, setView] = useState<View>("topology");
  const [theme, setTheme] = useState<Theme>(initialTheme());
  // undefined = lädt, null = nicht angemeldet
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined);

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  const toggleTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    applyTheme(next);
  };

  const logout = async () => {
    await authLogout().catch(() => {});
    setUser(null);
  };

  if (user === undefined) return <p style={{ padding: 20 }}>Lade…</p>;
  if (user === null) return <LoginView onLogin={setUser} />;

  return (
    <div className="app">
      <nav className="nav">
        <h1>NetBuddy</h1>
        {NAV.filter((n) => !n.adminOnly || user.role === "admin").map((n) => (
          <button
            key={n.key}
            className={`navitem ${view === n.key ? "active" : ""}`}
            onClick={() => setView(n.key)}
          >
            {n.label}
          </button>
        ))}
        <div className="spacer" />
        <div className="muted" style={{ fontSize: 12, padding: "0 6px 6px" }}>
          {user.username} · {user.role}
        </div>
        <button className="ghost" onClick={toggleTheme}>
          {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
        </button>
        <button className="ghost" onClick={logout} style={{ marginTop: 6 }}>
          ⎋ Abmelden
        </button>
      </nav>
      <main className="main">
        {view === "topology" && <TopologyView theme={theme} />}
        {view === "devices" && <DevicesView />}
        {view === "discovery" && <DiscoveryView />}
        {view === "sites" && <SitesView />}
        {view === "credentials" && <CredentialsView />}
        {view === "users" && <UsersView me={user} />}
        {view === "sso" && <SsoView />}
      </main>
    </div>
  );
}

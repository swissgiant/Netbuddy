import { useEffect, useState } from "react";
import type { OidcConfig } from "../api";
import { fetchOidcConfig, updateOidcConfig } from "../api";

type Form = {
  enabled: boolean;
  tenant_id: string;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
  group_admin_id: string;
  group_operator_id: string;
  group_viewer_id: string;
};

const EMPTY: Form = {
  enabled: false,
  tenant_id: "",
  client_id: "",
  client_secret: "",
  redirect_uri: "",
  group_admin_id: "",
  group_operator_id: "",
  group_viewer_id: "",
};

function toForm(c: OidcConfig): Form {
  return {
    enabled: c.enabled,
    tenant_id: c.tenant_id ?? "",
    client_id: c.client_id ?? "",
    client_secret: "", // nie vom Server geliefert; leer = behalten
    redirect_uri: c.redirect_uri ?? "",
    group_admin_id: c.group_admin_id ?? "",
    group_operator_id: c.group_operator_id ?? "",
    group_viewer_id: c.group_viewer_id ?? "",
  };
}

export function SsoView() {
  const [form, setForm] = useState<Form>(EMPTY);
  const [hasSecret, setHasSecret] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    fetchOidcConfig()
      .then((c) => {
        setForm(toForm(c));
        setHasSecret(c.has_secret);
      })
      .catch((e) => setError(String(e)));

  useEffect(() => {
    void load();
  }, []);

  const set = (k: keyof Form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setStatus(null);
    setError(null);
    try {
      const c = await updateOidcConfig({
        enabled: form.enabled,
        tenant_id: form.tenant_id || null,
        client_id: form.client_id || null,
        client_secret: form.client_secret || null,
        redirect_uri: form.redirect_uri || null,
        group_admin_id: form.group_admin_id || null,
        group_operator_id: form.group_operator_id || null,
        group_viewer_id: form.group_viewer_id || null,
      });
      setForm(toForm(c));
      setHasSecret(c.has_secret);
      setStatus("Gespeichert.");
    } catch (e) {
      setError(String(e));
    }
  };

  const field = (label: string, k: keyof Form, placeholder = "") => (
    <label style={{ display: "grid", gap: 4 }}>
      <span className="muted" style={{ fontSize: 12 }}>
        {label}
      </span>
      <input
        value={form[k] as string}
        placeholder={placeholder}
        onChange={(e) => set(k, e.target.value)}
      />
    </label>
  );

  return (
    <div style={{ maxWidth: 640 }}>
      <h2>🔐 SSO / Entra ID</h2>
      <p className="muted">
        Anmeldung über Microsoft Entra ID. Die Rolle ergibt sich aus der AAD-Gruppen-Mitgliedschaft
        (Admin ⊇ Operator ⊇ Viewer). Werte stammen aus <code>Setup-Entra-NetBuddy.ps1</code>. Das
        Client-Secret wird verschlüsselt gespeichert und nie wieder angezeigt.
      </p>

      <div className="card" style={{ display: "grid", gap: 12 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
          />
          <span>SSO aktiviert</span>
        </label>

        {field("Tenant ID", "tenant_id", "z.B. 00000000-0000-0000-0000-000000000000")}
        {field("Client ID", "client_id")}
        <label style={{ display: "grid", gap: 4 }}>
          <span className="muted" style={{ fontSize: 12 }}>
            Client Secret {hasSecret && <em>(gesetzt — leer lassen zum Behalten)</em>}
          </span>
          <input
            type="password"
            value={form.client_secret}
            placeholder={hasSecret ? "••••••••" : ""}
            onChange={(e) => set("client_secret", e.target.value)}
          />
        </label>
        {field(
          "Redirect URI",
          "redirect_uri",
          "https://bls-srv-netbuddy.bls.local/auth/callback",
        )}

        <hr style={{ width: "100%", opacity: 0.2 }} />
        <span className="muted" style={{ fontSize: 12 }}>
          Object-IDs der AAD-Sicherheitsgruppen → Rollen:
        </span>
        {field("Gruppe → Admin", "group_admin_id")}
        {field("Gruppe → Operator", "group_operator_id")}
        {field("Gruppe → Viewer", "group_viewer_id")}

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={save}>Speichern</button>
          {status && <span style={{ color: "var(--ok, green)" }}>{status}</span>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </div>
  );
}

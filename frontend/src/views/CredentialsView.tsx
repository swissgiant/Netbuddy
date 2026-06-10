import { useEffect, useState } from "react";
import type { Credential, CredentialCreate } from "../api";
import { createCredential, deleteCredential, fetchCredentials } from "../api";

type Kind = "ssh" | "api";

export function CredentialsView() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [kind, setKind] = useState<Kind>("ssh");
  const [form, setForm] = useState<CredentialCreate>({ name: "", ssh_port: 22 });
  const [siteOrOrg, setSiteOrOrg] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetchCredentials()
      .then(setCreds)
      .catch((e) => setError(String(e)));
  };
  useEffect(reload, []);

  const submit = async () => {
    setError(null);
    try {
      const body: CredentialCreate =
        kind === "ssh"
          ? { name: form.name, username: form.username, password: form.password, enable_password: form.enable_password, ssh_port: form.ssh_port }
          : { name: form.name, base_url: form.base_url, api_token: form.api_token, extra: siteOrOrg ? { site: siteOrOrg, org_id: siteOrOrg } : {} };
      await createCredential(body);
      setForm({ name: "", ssh_port: 22 });
      setSiteOrOrg("");
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Credential entfernen?")) return;
    await deleteCredential(id);
    reload();
  };

  const set = (k: keyof CredentialCreate, v: string) =>
    setForm({ ...form, [k]: k === "ssh_port" ? Number(v) : v });

  return (
    <div className="content">
      <h2>Credentials</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Credential anlegen</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <button className={kind === "ssh" ? "" : "ghost"} onClick={() => setKind("ssh")}>SSH</button>
          <button className={kind === "api" ? "" : "ghost"} onClick={() => setKind("api")}>API</button>
        </div>
        <div className="row">
          <input placeholder="Name" value={form.name} onChange={(e) => set("name", e.target.value)} />
          {kind === "ssh" ? (
            <>
              <input placeholder="username" value={form.username ?? ""} onChange={(e) => set("username", e.target.value)} />
              <input placeholder="password" type="password" value={form.password ?? ""} onChange={(e) => set("password", e.target.value)} />
              <input placeholder="enable (opt.)" type="password" value={form.enable_password ?? ""} onChange={(e) => set("enable_password", e.target.value)} />
              <input placeholder="ssh_port" style={{ width: 90 }} value={form.ssh_port ?? 22} onChange={(e) => set("ssh_port", e.target.value)} />
            </>
          ) : (
            <>
              <input placeholder="base_url (https://…)" value={form.base_url ?? ""} onChange={(e) => set("base_url", e.target.value)} />
              <input placeholder="api_token" type="password" value={form.api_token ?? ""} onChange={(e) => set("api_token", e.target.value)} />
              <input placeholder="site / org_id (opt.)" value={siteOrOrg} onChange={(e) => setSiteOrOrg(e.target.value)} />
            </>
          )}
          <button onClick={submit} disabled={!form.name}>Anlegen</button>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Vorhandene <span className="badge">{creds.length}</span></h3>
          <button className="ghost" onClick={reload}>↻</button>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Typ</th><th>Username / Base-URL</th><th>SSH-Port</th><th></th></tr></thead>
          <tbody>
            {creds.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td><span className="badge">{c.base_url ? "API" : "SSH"}</span></td>
                <td className="muted">{c.base_url ?? c.username ?? "—"}</td>
                <td className="muted">{c.base_url ? "—" : c.ssh_port}</td>
                <td><button className="danger" onClick={() => remove(c.id)}>entfernen</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ fontSize: 12 }}>Geheimnisse werden serverseitig verschlüsselt (Fernet) gespeichert und nie zurückgegeben.</p>
      </div>
    </div>
  );
}

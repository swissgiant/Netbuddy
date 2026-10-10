import { useEffect, useState } from "react";
import type { Credential, CredentialCreate, CredentialUpdate } from "../api";
import { createCredential, deleteCredential, fetchCredentials, updateCredential } from "../api";
import { Th, useSort } from "../sort";
import { PasswordstateImport } from "./PasswordstateImport";

type Kind = "ssh" | "api";

export function CredentialsView() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [kind, setKind] = useState<Kind>("ssh");
  const [form, setForm] = useState<CredentialCreate>({ name: "", ssh_port: 22 });
  const [siteOrOrg, setSiteOrOrg] = useState("");
  // Protokoll folgt dem Port: 22 = SSH, 23 = Telnet; nur bei anderen Ports erscheint die Auswahl.
  const [proto, setProto] = useState<"ssh" | "telnet">("ssh");
  const [error, setError] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [edit, setEdit] = useState<CredentialUpdate>({});

  const { sorted: sortedCreds, sort: credSort, toggle: credToggle } = useSort(creds, {
    target: (c) => c.base_url ?? c.username ?? null,
  });

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
          ? {
              name: form.name,
              username: form.username,
              password: form.password,
              enable_password: form.enable_password,
              ssh_port: form.ssh_port,
              // 22/23 sind eindeutig (Backend leitet ab); nur abweichende Ports brauchen die Wahl
              extra:
                form.ssh_port === 22 || form.ssh_port === 23 ? {} : { transport: proto },
            }
          : { name: form.name, base_url: form.base_url, api_token: form.api_token, extra: siteOrOrg ? { site: siteOrOrg, org_id: siteOrOrg, account_id: siteOrOrg } : {} };
      await createCredential(body);
      setForm({ name: "", ssh_port: 22 });
      setSiteOrOrg("");
      setProto("ssh");
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

  const startEdit = (c: Credential) => {
    setEditId(c.id);
    setEdit({ name: c.name, username: c.username ?? "", base_url: c.base_url ?? "",
      ssh_port: c.ssh_port, snmp_version: c.snmp_version ?? "",
      extra: c.extra ?? {} });
  };
  const saveEdit = async () => {
    if (!editId) return;
    setError(null);
    try {
      const body: CredentialUpdate = { ...edit };
      // leere Secrets nicht senden (bleiben unverändert); leere snmp_version -> null
      (["password", "api_token", "enable_password", "snmp_community"] as const).forEach((k) => {
        if (!body[k]) delete body[k];
      });
      await updateCredential(editId, body);
      setEditId(null); setEdit({}); reload();
    } catch (e) { setError(String(e)); }
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
              <label className="muted" style={{ fontSize: 12 }}>
                Port{" "}
                <input style={{ width: 70 }} value={form.ssh_port ?? 22}
                  onChange={(e) => set("ssh_port", e.target.value)} />
              </label>
              {form.ssh_port === 22 && <span className="badge">SSH</span>}
              {form.ssh_port === 23 && (
                <span className="badge" title="Telnet ist unverschlüsselt — nur read-only, Schreibzugriffe bleiben gesperrt.">
                  Telnet
                </span>
              )}
              {form.ssh_port !== 22 && form.ssh_port !== 23 && (
                <select value={proto} onChange={(e) => setProto(e.target.value as "ssh" | "telnet")}
                  title="Port weicht vom Standard ab — welches Protokoll spricht das Gerät?">
                  <option value="ssh">Protokoll: SSH</option>
                  <option value="telnet">Protokoll: Telnet</option>
                </select>
              )}
            </>
          ) : (
            <>
              <input placeholder="base_url (https://…)" value={form.base_url ?? ""} onChange={(e) => set("base_url", e.target.value)} />
              <input placeholder="api_token" type="password" value={form.api_token ?? ""} onChange={(e) => set("api_token", e.target.value)} />
              <input placeholder="site / org_id / account_id (opt.)" value={siteOrOrg} onChange={(e) => setSiteOrOrg(e.target.value)} />
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
          <thead>
            <tr>
              <Th k="name" sort={credSort} onSort={credToggle}>Name</Th>
              <Th k="kind" sort={credSort} onSort={credToggle}>Typ</Th>
              <Th k="target" sort={credSort} onSort={credToggle}>Username / Base-URL</Th>
              <Th k="ssh_port" sort={credSort} onSort={credToggle}>Port</Th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sortedCreds.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td><span className="badge">{c.kind.toUpperCase()}</span></td>
                <td className="muted">{c.base_url ?? c.username ?? "—"}</td>
                <td className="muted">{c.base_url ? "—" : c.ssh_port}</td>
                <td>
                  <button className="ghost" onClick={() => startEdit(c)}>✏️</button>{" "}
                  <button className="danger" onClick={() => remove(c.id)}>entfernen</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editId && (
          <div style={{ border: "1px solid var(--border,#444)", borderRadius: 8, padding: 12, marginTop: 10 }}>
            <h4 style={{ marginTop: 0 }}>Credential bearbeiten <span className="muted">(Secrets leer = unverändert)</span></h4>
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 6, maxWidth: 560 }}>
              <label>Name</label><input value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
              <label>Username</label><input value={edit.username ?? ""} onChange={(e) => setEdit({ ...edit, username: e.target.value })} />
              <label>Passwort</label><input type="password" placeholder="•••• (leer = behalten)" onChange={(e) => setEdit({ ...edit, password: e.target.value })} />
              <label>Base-URL</label><input value={edit.base_url ?? ""} onChange={(e) => setEdit({ ...edit, base_url: e.target.value })} />
              <label>API-Token</label><input type="password" placeholder="•••• (leer = behalten)" onChange={(e) => setEdit({ ...edit, api_token: e.target.value })} />
              <label>SSH-Port</label><input type="number" value={edit.ssh_port ?? 22} onChange={(e) => setEdit({ ...edit, ssh_port: Number(e.target.value) })} />
              <label>SNMP-Community</label><input type="password" placeholder="•••• (leer = behalten)" onChange={(e) => setEdit({ ...edit, snmp_community: e.target.value })} />
              <label>SNMP-Version</label>
              <select value={edit.snmp_version ?? ""} onChange={(e) => setEdit({ ...edit, snmp_version: e.target.value })}>
                <option value="">—</option><option value="v1">v1</option><option value="v2c">v2c</option><option value="v3">v3</option>
              </select>
            </div>
            <div style={{ marginTop: 8 }}>
              <button onClick={saveEdit}>Speichern</button>{" "}
              <button className="ghost" onClick={() => { setEditId(null); setEdit({}); }}>Abbrechen</button>
            </div>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12 }}>Geheimnisse werden serverseitig verschlüsselt (Fernet) gespeichert und nie zurückgegeben.</p>
      </div>
      <PasswordstateImport onImported={reload} />
    </div>
  );
}

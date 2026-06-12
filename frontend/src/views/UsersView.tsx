import { useEffect, useState } from "react";
import type { AuthUser } from "../api";
import { createUser, deleteUser, fetchUsers } from "../api";
import { Th, useSort } from "../sort";

const ROLES = ["viewer", "operator", "admin"];
const ROLE_HINT: Record<string, string> = {
  viewer: "nur lesen",
  operator: "lesen + suchen/ändern",
  admin: "alles inkl. Benutzer",
};

export function UsersView({ me }: { me: AuthUser }) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);

  const { sorted: sortedUsers, sort, toggle } = useSort(users);

  const reload = () => {
    fetchUsers()
      .then(setUsers)
      .catch((e) => setError(String(e)));
  };
  useEffect(reload, []);

  const submit = async () => {
    setError(null);
    try {
      await createUser(username, password, role);
      setUsername("");
      setPassword("");
      setRole("viewer");
      reload();
    } catch (e) {
      setError(String(e));
    }
  };

  const remove = async (user: AuthUser) => {
    if (user.id === me.id) {
      alert("Du kannst dich nicht selbst löschen.");
      return;
    }
    if (!confirm(`Benutzer ${user.username} löschen?`)) return;
    await deleteUser(user.id);
    reload();
  };

  return (
    <div className="content">
      <h2>Benutzer</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Benutzer anlegen</h3>
        <div className="row">
          <input placeholder="Benutzername" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input placeholder="Passwort" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r} — {ROLE_HINT[r]}</option>
            ))}
          </select>
          <button onClick={submit} disabled={!username || !password}>Anlegen</button>
        </div>
      </div>

      <div className="card">
        <h3>Vorhanden <span className="badge">{users.length}</span></h3>
        <table>
          <thead>
            <tr>
              <Th k="username" sort={sort} onSort={toggle}>Benutzername</Th>
              <Th k="role" sort={sort} onSort={toggle}>Rolle</Th>
              <Th k="enabled" sort={sort} onSort={toggle}>Aktiv</Th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sortedUsers.map((u) => (
              <tr key={u.id}>
                <td>{u.username}{u.id === me.id && <span className="muted"> (du)</span>}</td>
                <td><span className="badge">{u.role}</span> <span className="muted">{ROLE_HINT[u.role]}</span></td>
                <td>{u.enabled ? "✅" : "⛔"}</td>
                <td><button className="danger" onClick={() => remove(u)} disabled={u.id === me.id}>löschen</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

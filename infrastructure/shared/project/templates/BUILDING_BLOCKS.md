# Building blocks already in this workspace

Tested generic code. Use it instead of rewriting it; replace a block only when a
requirement needs something it cannot do. No block adds a dependency.

## Backend (`backend/src/lib/`)

- `http.ts`: throw `badRequest(msg, fields?)`, `unauthorized()`, `forbidden()`, `notFound()`,
  `conflict(msg, fields?)` (or `new HttpError(status, msg, fields?)`) from any route, sync or async. `apiErrors` turns them into
  `{ "error": msg, "fields"?: {...} }` with the right status; end `registerApis` with
  `app.use(apiErrors)`. `text(body, "username", { min, max, pattern, optional, raw, label })`
  reads and validates one body field (`raw: true` for passwords).
- `password.ts`: `hashPassword(password)`, `verifyPassword(password, storedHash)`. Same format
  as `seed_password_hash('...')` in `db/seeds/*.sql`, so seeded accounts can sign in.
- `session.ts`: `const sessions = createSessions(connection)` once in `registerApis`, then
  `sessions.start(response, userId)`, `sessions.userId(request)` (id or null, read-only),
  `sessions.require(request)` (id or 401), `sessions.end(request, response)`. Rows live in
  table `sessions(token, user_id, created_at)` behind an HttpOnly cookie; do not declare
  another `sessions` table. To seed a session, add a `db/tables/*.sql` file containing
  `sessionTableSql()`'s statement and insert `(token, user_id)` rows in a seed.
- Database: one `db/tables/NAME.sql` per table, listed in dependency order in `tableFiles`
  (`db/initialize.ts`); rows that must exist at startup go in `db/seeds/*.sql`, listed in
  `seedFiles` (`db/seed.ts`). Both run at every start: use `CREATE TABLE IF NOT EXISTS`
  and `INSERT OR IGNORE`.

```ts
// backend/src/api/register.ts
export function registerApis(app: Express, connection: Database.Database): void {
  const sessions = createSessions(connection);
  app.post("/api/login", (request, response) => {
    const username = text(request.body, "username");
    const user = connection.prepare("SELECT id, password_hash FROM users WHERE username = ?").get(username) as
      { id: number; password_hash: string } | undefined;
    if (!user || !verifyPassword(text(request.body, "password", { raw: true }), user.password_hash))
      throw unauthorized("Invalid username or password");
    sessions.start(response, user.id);
    response.json({ username });
  });
  app.use(apiErrors);
}
```

## Frontend (`frontend/src/lib/`)

- `api.ts`: `api.get<T>(path)`, `api.post<T>(path, body)`, `put`, `patch`, `delete`; a failed
  call throws `ApiError` (`status`, `message`, `fields`). `useResource<T>(path)` gives
  `{ data, error, loading, reload }`; `data` is null until resolved, never a stale value.
- `router.tsx`: `<Routes routes={{ "/": () => <Home />, "/items/:id": p => <Item id={p.id} /> }}
  fallback={<NotFound />} />`, `<Link to="/register">Register</Link>` (a real link), and
  `navigate("/")` after a successful action. Every route is a reloadable URL.
- `form.tsx`: `TextField`, `SelectField`, `RadioGroup`, `Checkbox`, `FormError`, `SubmitButton`.
  Each control's accessible name is exactly its `label`, so pass the label text as the
  requirement writes it. Show a failed submission in one `<FormError message={...} />`
  (the form's only `role="alert"`). An input of `type="date"` or `"password"` is not exposed as a
  textbox; keep `type="text"` when the requirement treats the field as plain text entry.
- `layout.tsx`: `<Layout header={...} footer={...}>`. Tailwind CSS is configured (`style.css`).

```tsx
const [error, setError] = useState<string | null>(null);
async function submit(event: FormEvent) {
  event.preventDefault();
  try { await api.post("/api/login", { username, password }); navigate("/"); }
  catch (failure) { setError(errorMessage(failure)); }
}
return <form onSubmit={submit}>
  <TextField label="Username" value={username} onChange={e => setUsername(e.target.value)} />
  <TextField label="Password" type="password" value={password} onChange={e => setPassword(e.target.value)} />
  <FormError message={error} /><SubmitButton>Login</SubmitButton>
</form>;
```

SQLite in this template (better-sqlite3, synchronous):
- One `CREATE TABLE IF NOT EXISTS` file per table under `backend/src/db/tables/`; list the filenames in
  dependency order in `tableFiles` (`db/initialize.ts`). Referenced tables come first; foreign keys are enforced.
- Records the requirements describe as already existing ("the database contains ...", "the account X exists")
  are startup data: put idempotent `INSERT OR IGNORE` rows in `backend/src/db/seeds/*.sql` and list them in
  `seedFiles` (`db/seed.ts`). Use `seed_password_hash('plain')` for seeded passwords, never plaintext.
- Initialization runs at every start on a possibly existing database: it must not fail or duplicate rows.
- Enforce uniqueness with `UNIQUE` constraints and translate the constraint error into the required rejection;
  a check-then-insert alone accepts duplicates under concurrent requests.
- Use parameters (`?`), never string concatenation. Wrap multi-statement changes in `connection.transaction`.
- A rejected operation must leave no partial row: verify with database_query after an http_request.

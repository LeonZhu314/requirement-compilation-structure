import { describe, it, expect } from "vitest";
import request from "supertest";
import { randomUUID } from "node:crypto";
import { createApp } from "../../backend/src/app.js";
import { getDatabase } from "../../backend/src/db/client.js";

type RegistrationBody = {
  nationality: string;
  name: string;
  passport_number: string;
  passport_expiration_date: string;
  date_of_birth: string;
  gender: "Male" | "Female";
  username: string;
  password: string;
  confirm_password: string;
  email: string;
  agreed_to_terms: boolean;
};

const STRONG_PASSWORD = "Str0ng!Passw0rd12";

function uniqueToken(): string {
  return randomUUID().replace(/-/g, "").slice(0, 10);
}

function registrationBody(overrides: Partial<RegistrationBody> = {}): RegistrationBody {
  const token = uniqueToken();
  return {
    nationality: "Vietnam",
    name: "Integration Traveler",
    passport_number: "AB123456",
    passport_expiration_date: "2035-01-01",
    date_of_birth: "1990-01-01",
    gender: "Male",
    username: `int_${token}`,
    password: STRONG_PASSWORD,
    confirm_password: STRONG_PASSWORD,
    email: `int_${token}@example.com`,
    agreed_to_terms: true,
    ...overrides,
  };
}

function accountRow(username: string) {
  return getDatabase()
    .prepare('SELECT "id", "username", "email", "password", "nationality", "gender" FROM "user_account" WHERE "username" = ?')
    .get(username) as
    | {
        id: string;
        username: string;
        email: string;
        password: string;
        nationality: string;
        gender: string;
      }
    | undefined;
}

function accountCountForEmail(email: string): number {
  const row = getDatabase()
    .prepare('SELECT COUNT(*) AS "count" FROM "user_account" WHERE "email" = ? COLLATE NOCASE')
    .get(email) as { count: number };
  return row.count;
}

function sessionCount(accountId: string): number {
  const row = getDatabase()
    .prepare('SELECT COUNT(*) AS "count" FROM "session" WHERE "user_account_id" = ?')
    .get(accountId) as { count: number };
  return row.count;
}

describe("POST /api/register (REQ-2)", () => {
  it("persists the account, creates a session and signs the visitor in", async () => {
    const app = createApp();
    const agent = request.agent(app);
    const body = registrationBody();

    const response = await agent.post("/api/register").send(body);

    expect(response.status).toBeGreaterThanOrEqual(200);
    expect(response.status).toBeLessThan(300);
    expect(response.body.username).toBe(body.username);
    expect(response.body.error).toBeUndefined();
    expect(response.headers["set-cookie"]).toBeDefined();

    const account = accountRow(body.username);
    expect(account).toBeDefined();
    expect(account!.email).toBe(body.email);
    expect(account!.nationality).toBe("Vietnam");
    expect(account!.gender).toBe("Male");
    expect(account!.password).not.toBe(body.password);
    expect(account!.password.length).toBeGreaterThan(0);
    expect(sessionCount(account!.id)).toBe(1);

    const session = await agent.get("/api/session");
    expect(session.status).toBe(200);
    expect(session.body).toEqual({ authenticated: true, username: body.username });
  });

  it("rejects submission without agreement and creates no account or session", async () => {
    const app = createApp();
    const body = registrationBody({ agreed_to_terms: false });

    const response = await request(app).post("/api/register").send(body);

    expect(typeof response.body.error).toBe("string");
    expect(response.body.username).toBeUndefined();
    expect(accountRow(body.username)).toBeUndefined();
  });

  it("rejects a mismatched password confirmation without creating an account", async () => {
    const app = createApp();
    const body = registrationBody({ confirm_password: "Other!Passw0rd99" });

    const response = await request(app).post("/api/register").send(body);

    expect(typeof response.body.error).toBe("string");
    expect(accountRow(body.username)).toBeUndefined();

    const session = await request(app).get("/api/session");
    expect(session.body).toEqual({ authenticated: false, username: null });
  });

  it("rejects a weak password", async () => {
    const app = createApp();
    const body = registrationBody({ password: "weakpassword", confirm_password: "weakpassword" });

    const response = await request(app).post("/api/register").send(body);

    expect(typeof response.body.error).toBe("string");
    expect(accountRow(body.username)).toBeUndefined();
  });

  it("rejects a duplicate username", async () => {
    const app = createApp();
    const first = registrationBody();

    const created = await request(app).post("/api/register").send(first);
    expect(created.body.username).toBe(first.username);

    const duplicate = registrationBody({ username: first.username });
    const response = await request(app).post("/api/register").send(duplicate);

    expect(typeof response.body.error).toBe("string");
    expect(response.body.username).toBeUndefined();
    expect(accountCountForEmail(duplicate.email)).toBe(0);
  });

  it("rejects a duplicate email regardless of letter case", async () => {
    const app = createApp();
    const first = registrationBody();

    const created = await request(app).post("/api/register").send(first);
    expect(created.body.username).toBe(first.username);

    const duplicate = registrationBody({ email: first.email.toUpperCase() });
    const response = await request(app).post("/api/register").send(duplicate);

    expect(typeof response.body.error).toBe("string");
    expect(response.body.username).toBeUndefined();
    expect(accountRow(duplicate.username)).toBeUndefined();
  });

  it("keeps previously registered accounts usable by other visitors after a successful registration", async () => {
    const app = createApp();
    const firstBody = registrationBody();
    const secondBody = registrationBody();

    const firstResponse = await request(app).post("/api/register").send(firstBody);
    expect(firstResponse.body.username).toBe(firstBody.username);
    const secondResponse = await request(app).post("/api/register").send(secondBody);
    expect(secondResponse.body.username).toBe(secondBody.username);

    expect(accountRow(firstBody.username)).toBeDefined();
    expect(accountRow(secondBody.username)).toBeDefined();
  });
});

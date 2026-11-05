import { describe, it, expect } from "vitest";
import request from "supertest";
import { createApp } from "../../backend/src/app.js";

function validRegistration() {
  return {
    nationality: "Vietnam",
    name: "Req One Traveler",
    passport_number: "AB123456",
    passport_expiration_date: "2035-01-01",
    date_of_birth: "1990-01-01",
    gender: "Male",
    username: "req1_traveler",
    password: "Str0ng!Passw0rd12",
    confirm_password: "Str0ng!Passw0rd12",
    email: "req1_traveler@example.com",
    agreed_to_terms: true,
  };
}

describe("GET /api/session (REQ-1)", () => {
  it("reports unauthenticated with a null username when no session cookie is present", async () => {
    const app = createApp();
    const response = await request(app).get("/api/session");
    expect(response.status).toBe(200);
    expect(response.body).toEqual({ authenticated: false, username: null });
  });
});

describe("REQ-1 account session lifecycle", () => {
  it("shows the saved username after registration and restores the guest state after sign out", async () => {
    const app = createApp();
    const agent = request.agent(app);

    const register = await agent.post("/api/register").send(validRegistration());
    expect(register.status).toBeGreaterThanOrEqual(200);
    expect(register.status).toBeLessThan(300);
    expect(register.body.username).toBe("req1_traveler");

    const afterRegister = await agent.get("/api/session");
    expect(afterRegister.status).toBe(200);
    expect(afterRegister.body).toEqual({ authenticated: true, username: "req1_traveler" });

    const signOut = await agent.delete("/api/session");
    expect(signOut.status).toBeGreaterThanOrEqual(200);
    expect(signOut.status).toBeLessThan(300);

    const afterSignOut = await agent.get("/api/session");
    expect(afterSignOut.status).toBe(200);
    expect(afterSignOut.body).toEqual({ authenticated: false, username: null });
  });

  it("sign out succeeds even when the visitor is not authenticated", async () => {
    const app = createApp();
    const response = await request(app).delete("/api/session");
    expect(response.status).toBeGreaterThanOrEqual(200);
    expect(response.status).toBeLessThan(300);
  });
});

import { describe, it, expect } from "vitest";
import { randomUUID } from "node:crypto";
import { ResolveActiveSession } from "../../backend/src/features/train-ticket-booking-demo/services/ResolveActiveSession.js";
import { RevokeSession } from "../../backend/src/features/train-ticket-booking-demo/services/RevokeSession.js";
import { FindSessionAccountById } from "../../backend/src/features/train-ticket-booking-demo/repositories/FindSessionAccountById.js";
import { DeleteSessionById } from "../../backend/src/features/train-ticket-booking-demo/repositories/DeleteSessionById.js";

describe("REQ-1 ResolveActiveSession", () => {
  it("treats an absent session id as unauthenticated", async () => {
    await expect(ResolveActiveSession({})).resolves.toEqual({ authenticated: false, username: null });
  });

  it("treats a null session id as unauthenticated", async () => {
    await expect(ResolveActiveSession({ session_id: null })).resolves.toEqual({ authenticated: false, username: null });
  });

  it("treats an unknown session id as unauthenticated", async () => {
    await expect(ResolveActiveSession({ session_id: randomUUID() })).resolves.toEqual({ authenticated: false, username: null });
  });
});

describe("REQ-1 FindSessionAccountById", () => {
  it("reports not found for an unknown session id", async () => {
    await expect(FindSessionAccountById({ session_id: randomUUID() })).resolves.toEqual({ found: false, username: null });
  });
});

describe("REQ-1 RevokeSession sign out", () => {
  it("succeeds without a session id", async () => {
    await expect(RevokeSession({})).resolves.toEqual({});
  });

  it("succeeds with a null session id", async () => {
    await expect(RevokeSession({ session_id: null })).resolves.toEqual({});
  });

  it("succeeds with an unknown session id", async () => {
    await expect(RevokeSession({ session_id: randomUUID() })).resolves.toEqual({});
  });
});

describe("REQ-1 DeleteSessionById", () => {
  it("succeeds whether or not the session row exists", async () => {
    await expect(DeleteSessionById({ session_id: randomUUID() })).resolves.toEqual({});
  });
});

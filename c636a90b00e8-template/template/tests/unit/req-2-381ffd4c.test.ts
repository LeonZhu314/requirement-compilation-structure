import { describe, it, expect } from "vitest";
import { randomUUID } from "node:crypto";
import { ValidateRegistration } from "../../backend/src/features/train-ticket-booking-demo/services/ValidateRegistration.js";
import { CreateTravelerAccount, type CreateTravelerAccountInput } from "../../backend/src/features/train-ticket-booking-demo/services/CreateTravelerAccount.js";
import { CheckAccountUniqueness } from "../../backend/src/features/train-ticket-booking-demo/services/CheckAccountUniqueness.js";
import { FindAccountByUsernameOrEmail } from "../../backend/src/features/train-ticket-booking-demo/repositories/FindAccountByUsernameOrEmail.js";
import { getDatabase } from "../../backend/src/db/client.js";

const STRONG_PASSWORD = "Str0ng!Passw0rd12";

function uniqueToken(): string {
  return randomUUID().replace(/-/g, "").slice(0, 10);
}

function registrationInput(overrides: Partial<CreateTravelerAccountInput> = {}): CreateTravelerAccountInput {
  const token = uniqueToken();
  return {
    nationality: "Vietnam",
    name: "Unit Traveler",
    passport_number: "AB123456",
    passport_expiration_date: "2035-01-01",
    date_of_birth: "1990-01-01",
    gender: "Male",
    username: `unit_${token}`,
    password: STRONG_PASSWORD,
    confirm_password: STRONG_PASSWORD,
    email: `unit_${token}@example.com`,
    agreed_to_terms: true,
    ...overrides,
  };
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function accountRow(username: string) {
  return getDatabase()
    .prepare('SELECT "id", "username", "email", "password" FROM "user_account" WHERE "username" = ?')
    .get(username) as { id: string; username: string; email: string; password: string } | undefined;
}

function sessionCount(accountId: string): number {
  const row = getDatabase()
    .prepare('SELECT COUNT(*) AS "count" FROM "session" WHERE "user_account_id" = ?')
    .get(accountId) as { count: number };
  return row.count;
}

describe("REQ-2 ValidateRegistration accepts a fully valid registration", () => {
  it("returns valid with no error for agreed, well-formed input", async () => {
    const result = await ValidateRegistration(registrationInput());
    expect(result).toEqual({ valid: true, error: null });
  });
});

describe("REQ-2 ValidateRegistration rejects invalid input with an error and no writes", () => {
  it("requires the agreement checkbox to be checked", async () => {
    const input = registrationInput({ agreed_to_terms: false });
    const result = await ValidateRegistration(input);
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
    expect(accountRow(input.username)).toBeUndefined();
  });

  it("rejects a name with fewer than 2 non-whitespace characters", async () => {
    const result = await ValidateRegistration(registrationInput({ name: " A " }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects a name with more than 100 non-whitespace characters", async () => {
    const result = await ValidateRegistration(registrationInput({ name: "A".repeat(101) }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects a passport number shorter than 6 characters", async () => {
    const result = await ValidateRegistration(registrationInput({ passport_number: "AB123" }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects a passport number with characters other than ASCII letters, digits or hyphens", async () => {
    const result = await ValidateRegistration(registrationInput({ passport_number: "AB12345!" }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("accepts a hyphenated passport number within the length limits", async () => {
    const result = await ValidateRegistration(registrationInput({ passport_number: "AB-123-456" }));
    expect(result).toEqual({ valid: true, error: null });
  });

  it("rejects a date of birth that is not earlier than the current date", async () => {
    const todayResult = await ValidateRegistration(registrationInput({ date_of_birth: today() }));
    expect(todayResult.valid).toBe(false);
    expect(typeof todayResult.error).toBe("string");

    const futureResult = await ValidateRegistration(registrationInput({ date_of_birth: "2999-01-01" }));
    expect(futureResult.valid).toBe(false);
    expect(typeof futureResult.error).toBe("string");
  });

  it("rejects a passport expiration date that is not later than the current date", async () => {
    const pastResult = await ValidateRegistration(registrationInput({ passport_expiration_date: "2000-01-01" }));
    expect(pastResult.valid).toBe(false);
    expect(typeof pastResult.error).toBe("string");

    const todayResult = await ValidateRegistration(registrationInput({ passport_expiration_date: today() }));
    expect(todayResult.valid).toBe(false);
    expect(typeof todayResult.error).toBe("string");
  });

  it("rejects a username outside the 3-32 character ASCII rule", async () => {
    const tooShort = await ValidateRegistration(registrationInput({ username: "ab" }));
    expect(tooShort.valid).toBe(false);
    expect(typeof tooShort.error).toBe("string");

    const badCharacter = await ValidateRegistration(registrationInput({ username: "bad user!" }));
    expect(badCharacter.valid).toBe(false);
    expect(typeof badCharacter.error).toBe("string");
  });

  it("rejects an invalid email address", async () => {
    const result = await ValidateRegistration(registrationInput({ email: "not-an-email" }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects an email address longer than 254 characters", async () => {
    const longEmail = `${"a".repeat(250)}@ex.com`;
    const result = await ValidateRegistration(registrationInput({ email: longEmail }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects a password without a special character", async () => {
    const result = await ValidateRegistration(
      registrationInput({ password: "Str0ngPassw0rd12", confirm_password: "Str0ngPassw0rd12" }),
    );
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects a password shorter than 12 characters", async () => {
    const short = "Ab1!Ab1!";
    const result = await ValidateRegistration(registrationInput({ password: short, confirm_password: short }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });

  it("rejects when the confirmation password differs", async () => {
    const result = await ValidateRegistration(registrationInput({ confirm_password: "Other!Passw0rd99" }));
    expect(result.valid).toBe(false);
    expect(typeof result.error).toBe("string");
  });
});

describe("REQ-2 ValidateRegistration rejects duplicate accounts", () => {
  it("rejects a username that already exists", async () => {
    const existing = registrationInput();
    const created = await CreateTravelerAccount(existing);
    expect(created.error).toBeNull();
    expect(created.username).toBe(existing.username);

    const duplicate = await ValidateRegistration(registrationInput({ username: existing.username }));
    expect(duplicate.valid).toBe(false);
    expect(typeof duplicate.error).toBe("string");
  });

  it("rejects an email that already exists regardless of letter case", async () => {
    const existing = registrationInput();
    const created = await CreateTravelerAccount(existing);
    expect(created.error).toBeNull();

    const duplicate = await ValidateRegistration(registrationInput({ email: existing.email.toUpperCase() }));
    expect(duplicate.valid).toBe(false);
    expect(typeof duplicate.error).toBe("string");
  });
});

describe("REQ-2 CreateTravelerAccount persists the account and session", () => {
  it("stores the account with a hashed password, creates a session and returns the username", async () => {
    const input = registrationInput();
    const result = await CreateTravelerAccount(input);

    expect(result.error).toBeNull();
    expect(result.username).toBe(input.username);
    expect(typeof result.session_id).toBe("string");
    expect((result.session_id ?? "").length).toBeGreaterThan(0);

    const account = accountRow(input.username);
    expect(account).toBeDefined();
    expect(account!.password).not.toBe(input.password);
    expect(account!.password.length).toBeGreaterThan(0);
    expect(account!.email).toBe(input.email);

    expect(sessionCount(account!.id)).toBe(1);
  });

  it("creates neither an account nor a session when validation fails", async () => {
    const input = registrationInput({ agreed_to_terms: false });
    const result = await CreateTravelerAccount(input);

    expect(result.username).toBeNull();
    expect(result.session_id).toBeNull();
    expect(typeof result.error).toBe("string");
    expect(accountRow(input.username)).toBeUndefined();
  });

  it("creates no second account for a duplicate username", async () => {
    const first = registrationInput();
    const created = await CreateTravelerAccount(first);
    expect(created.error).toBeNull();

    const duplicate = await CreateTravelerAccount(registrationInput({ username: first.username }));
    expect(duplicate.username).toBeNull();
    expect(duplicate.session_id).toBeNull();
    expect(typeof duplicate.error).toBe("string");
  });
});

describe("REQ-2 account uniqueness lookups", () => {
  it("reports both flags false for an unused username and email", async () => {
    const token = uniqueToken();
    const result = await CheckAccountUniqueness({
      username: `fresh_${token}`,
      email: `fresh_${token}@example.com`,
    });
    expect(result).toEqual({ username_taken: false, email_taken: false });
  });

  it("reports a taken username under exact comparison", async () => {
    const input = registrationInput();
    const created = await CreateTravelerAccount(input);
    expect(created.error).toBeNull();

    const result = await FindAccountByUsernameOrEmail({
      username: input.username,
      email: `other_${uniqueToken()}@example.com`,
    });
    expect(result).toEqual({ username_taken: true, email_taken: false });
  });

  it("reports a taken email ignoring letter case", async () => {
    const input = registrationInput();
    const created = await CreateTravelerAccount(input);
    expect(created.error).toBeNull();

    const result = await FindAccountByUsernameOrEmail({
      username: `other_${uniqueToken()}`,
      email: input.email.toUpperCase(),
    });
    expect(result).toEqual({ username_taken: false, email_taken: true });
  });
});

import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

// Same "scrypt$salt$digest" format as seed_password_hash() in db/seed.ts and
// fixturePasswordHash() in tests/support/context.ts: seeded accounts verify here.

export function hashPassword(password: string): string {
  const salt = randomBytes(16);
  return `scrypt$${salt.toString("hex")}$${scryptSync(password, salt, 64).toString("hex")}`;
}

export function verifyPassword(password: string, stored: unknown): boolean {
  if (typeof stored !== "string") return false;
  const [scheme, salt, digest] = stored.split("$");
  if (scheme !== "scrypt" || !salt || !digest || !/^[0-9a-f]+$/i.test(salt + digest)) return false;
  const expected = Buffer.from(digest, "hex");
  const actual = scryptSync(password, Buffer.from(salt, "hex"), expected.length);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

import { CheckAccountUniqueness } from "./CheckAccountUniqueness.js";

export type ValidateRegistrationInput = { "nationality": string; "name": string; "passport_number": string; "passport_expiration_date": string; "date_of_birth": string; "gender": ("Male" | "Female"); "username": string; "password": string; "confirm_password": string; "email": string; "agreed_to_terms": boolean; };
export type ValidateRegistrationOutput = { "valid": boolean; "error": (string | null); };

function fail(error: string): ValidateRegistrationOutput {
  return { valid: false, error };
}

function todayDateOnly(): string {
  return new Date().toISOString().slice(0, 10);
}

function dateOnly(value: string): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function isValidEmail(value: string): boolean {
  if (typeof value !== "string") return false;
  if (value.length === 0 || value.length > 254) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function isStrongPassword(value: string): boolean {
  if (typeof value !== "string") return false;
  if (value.length < 12 || value.length > 128) return false;
  if (!/[A-Z]/.test(value)) return false;
  if (!/[a-z]/.test(value)) return false;
  if (!/[0-9]/.test(value)) return false;
  if (!/[^A-Za-z0-9]/.test(value)) return false;
  return true;
}

export async function ValidateRegistration(input: ValidateRegistrationInput): Promise<ValidateRegistrationOutput> {
  if (input.agreed_to_terms !== true) {
    return fail("You must agree to the Terms of Service and Privacy Policy.");
  }

  const nameNonWhitespace = (input.name ?? "").replace(/\s/g, "").length;
  if (nameNonWhitespace < 2 || nameNonWhitespace > 100) {
    return fail("Name must contain between 2 and 100 non-whitespace characters.");
  }

  if (!/^[A-Za-z0-9-]{6,30}$/.test(input.passport_number ?? "")) {
    return fail("Passport number must be 6-30 letters, digits or hyphens.");
  }

  const today = todayDateOnly();
  const dateOfBirth = dateOnly(input.date_of_birth);
  if (!dateOfBirth || dateOfBirth >= today) {
    return fail("Date of birth must be earlier than today.");
  }

  const expiration = dateOnly(input.passport_expiration_date);
  if (!expiration || expiration <= today) {
    return fail("Passport expiration date must be later than today.");
  }

  if (input.gender !== "Male" && input.gender !== "Female") {
    return fail("Gender must be Male or Female.");
  }

  if (!/^[A-Za-z0-9_-]{3,32}$/.test(input.username ?? "")) {
    return fail("Username must be 3-32 letters, digits, hyphens or underscores.");
  }

  if (!isValidEmail(input.email)) {
    return fail("Email must be a valid address of at most 254 characters.");
  }

  if (!isStrongPassword(input.password)) {
    return fail("Password must be 12-128 characters including an uppercase letter, a lowercase letter, a digit and a special character.");
  }

  if (input.password !== input.confirm_password) {
    return fail("Passwords must match.");
  }

  const uniqueness = await CheckAccountUniqueness({ username: input.username, email: input.email });
  if (uniqueness.username_taken) {
    return fail("That username is already taken.");
  }
  if (uniqueness.email_taken) {
    return fail("That email is already registered.");
  }

  return { valid: true, error: null };
}

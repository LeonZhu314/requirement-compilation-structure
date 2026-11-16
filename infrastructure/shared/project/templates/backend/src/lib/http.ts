import type { ErrorRequestHandler } from "express";

/** An expected failure with its HTTP status. Throw it from any route, sync or async. */
export class HttpError extends Error {
  readonly status: number;
  readonly fields?: Record<string, string>;

  constructor(status: number, message: string, fields?: Record<string, string>) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

export const badRequest = (message: string, fields?: Record<string, string>) => new HttpError(400, message, fields);
export const unauthorized = (message = "Authentication required") => new HttpError(401, message);
export const forbidden = (message = "Not allowed") => new HttpError(403, message);
export const notFound = (message = "Not found") => new HttpError(404, message);
export const conflict = (message: string, fields?: Record<string, string>) => new HttpError(409, message, fields);

/**
 * Uniform JSON errors: { "error": message, "fields"?: { name: message } }.
 * Register it after the routes: `app.use(apiErrors)` as the last line of registerApis.
 */
export const apiErrors: ErrorRequestHandler = (error, _request, response, next) => {
  if (response.headersSent) return next(error);
  if (error instanceof HttpError) {
    response.status(error.status).json({ error: error.message, ...(error.fields ? { fields: error.fields } : {}) });
    return;
  }
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status === "number" && status >= 400 && status < 500) {
    response.status(status).json({ error: "Invalid request" });   // Malformed JSON, oversized body.
    return;
  }
  console.error(error);
  response.status(500).json({ error: "Internal server error" });
};

export interface TextOptions {
  /** Name shown in messages; defaults to the key. */
  label?: string;
  optional?: boolean;
  min?: number;
  max?: number;
  pattern?: RegExp;
  /** Keep surrounding spaces (passwords). */
  raw?: boolean;
}

/** One text field of a JSON body, trimmed and checked; throws a 400 naming the field. */
export function text(body: unknown, key: string, options: TextOptions = {}): string {
  const label = options.label ?? key;
  const found = body !== null && typeof body === "object" ? (body as Record<string, unknown>)[key] : undefined;
  const fail = (message: string) => badRequest(message, { [key]: message });
  if (found !== undefined && found !== null && typeof found !== "string") throw fail(`${label} must be text`);
  const value = typeof found === "string" ? (options.raw ? found : found.trim()) : "";
  if (!value) {
    if (options.optional) return "";
    throw fail(`${label} is required`);
  }
  if (options.min !== undefined && value.length < options.min) throw fail(`${label} must be at least ${options.min} characters`);
  if (options.max !== undefined && value.length > options.max) throw fail(`${label} must be at most ${options.max} characters`);
  if (options.pattern && !options.pattern.test(value)) throw fail(`${label} is not valid`);
  return value;
}

import type Database from "better-sqlite3";
import type { Request, Response } from "express";
import { randomBytes } from "node:crypto";
import { unauthorized } from "./http.js";

export type UserId = string | number;

export interface SessionOptions {
  /** Cookie name; default "session". */
  cookie?: string;
  /** Table name; default "sessions". */
  table?: string;
  /** Cookie lifetime; default 30 days. */
  maxAgeSeconds?: number;
}

/** Columns of the session table, for a db/tables/*.sql file when sessions must be seeded. */
export const sessionTableSql = (table = "sessions") =>
  `CREATE TABLE IF NOT EXISTS ${table} (token TEXT PRIMARY KEY, user_id NOT NULL, ` +
  `created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);`;

/**
 * Server-side sessions in SQLite behind an HttpOnly cookie; no extra dependency.
 * A session exists only as a row: an unknown or deleted token is simply signed out.
 */
export function createSessions(connection: Database.Database, options: SessionOptions = {}) {
  const cookie = options.cookie ?? "session";
  const table = options.table ?? "sessions";
  const maxAge = (options.maxAgeSeconds ?? 30 * 24 * 3600) * 1000;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(table) || !/^[A-Za-z0-9_-]+$/.test(cookie)) throw new Error("Invalid session names");
  connection.exec(sessionTableSql(table));
  const insert = connection.prepare(`INSERT INTO ${table} (token, user_id) VALUES (?, ?)`);
  const select = connection.prepare(`SELECT user_id FROM ${table} WHERE token = ?`);
  const remove = connection.prepare(`DELETE FROM ${table} WHERE token = ?`);

  function token(request: Request): string | null {
    for (const part of (request.headers.cookie ?? "").split(";")) {
      const separator = part.indexOf("=");
      if (separator > 0 && part.slice(0, separator).trim() === cookie) {
        try {
          return decodeURIComponent(part.slice(separator + 1).trim()) || null;
        } catch {
          return null;
        }
      }
    }
    return null;
  }

  return {
    /** Create a session row for the user and set its cookie. */
    start(response: Response, userId: UserId): string {
      const value = randomBytes(32).toString("hex");
      insert.run(value, userId);
      response.cookie(cookie, value, { httpOnly: true, sameSite: "lax", path: "/", maxAge });
      return value;
    },
    /** The signed-in user id, or null without a recognized session. Read-only. */
    userId(request: Request): UserId | null {
      const value = token(request);
      const row = value ? (select.get(value) as { user_id: UserId } | undefined) : undefined;
      return row ? row.user_id : null;
    },
    /** The signed-in user id, or a 401 handled by apiErrors. */
    require(request: Request): UserId {
      const id = this.userId(request);
      if (id === null) throw unauthorized();
      return id;
    },
    /** Delete the current session row, if any, and clear the cookie. */
    end(request: Request, response: Response): void {
      const value = token(request);
      if (value) remove.run(value);
      response.clearCookie(cookie, { httpOnly: true, sameSite: "lax", path: "/" });
    },
  };
}

export type Sessions = ReturnType<typeof createSessions>;

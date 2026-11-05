import express from "express";
import { fileURLToPath } from "node:url";
import { GetCurrentSession } from "./features/train-ticket-booking-demo/controllers/GetCurrentSession.js";
import { SignOut } from "./features/train-ticket-booking-demo/controllers/SignOut.js";
import { RegisterAccount } from "./features/train-ticket-booking-demo/controllers/RegisterAccount.js";
const SESSION_COOKIE = "session_id";
function readSessionCookie(cookieHeader) {
    if (!cookieHeader)
        return undefined;
    for (const part of cookieHeader.split(";")) {
        const separator = part.indexOf("=");
        const name = (separator === -1 ? part : part.slice(0, separator)).trim();
        if (name !== SESSION_COOKIE)
            continue;
        const rawValue = separator === -1 ? "" : part.slice(separator + 1).trim();
        if (!rawValue)
            return undefined;
        try {
            return decodeURIComponent(rawValue);
        }
        catch {
            return rawValue;
        }
    }
    return undefined;
}
function issuedSessionCookie(sessionId) {
    return `${SESSION_COOKIE}=${encodeURIComponent(sessionId)}; Path=/; HttpOnly; SameSite=Lax`;
}
function clearedSessionCookie() {
    return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT`;
}
export function createApp() {
    const app = express();
    app.use(express.json());
    app.get("/__arc/health", (_request, response) => {
        response.json({ status: "ok" });
    });
    app.get("/api/session", async (request, response, next) => {
        try {
            const session = await GetCurrentSession({ session_id: readSessionCookie(request.headers.cookie) });
            response.status(200).json(session);
        }
        catch (error) {
            next(error);
        }
    });
    app.delete("/api/session", async (request, response, next) => {
        try {
            await SignOut({ session_id: readSessionCookie(request.headers.cookie) });
            response.setHeader("Set-Cookie", clearedSessionCookie());
            response.status(200).json({});
        }
        catch (error) {
            next(error);
        }
    });
    app.post("/api/register", async (request, response, next) => {
        try {
            const result = await RegisterAccount({ ...(request.body ?? {}) });
            if (result.error || !result.username || !result.session_id) {
                response.status(400).json({ error: result.error ?? "Registration failed." });
                return;
            }
            response.setHeader("Set-Cookie", issuedSessionCookie(result.session_id));
            response.status(200).json({ username: result.username });
        }
        catch (error) {
            next(error);
        }
    });
    app.use(express.static(fileURLToPath(new URL("../../frontend/dist/", import.meta.url))));
    app.use((request, response, next) => {
        if (request.method !== "GET" || request.path.startsWith("/api")) {
            next();
            return;
        }
        response.sendFile(fileURLToPath(new URL("../../frontend/dist/index.html", import.meta.url)));
    });
    app.use((error, _request, response, _next) => {
        const message = error instanceof Error ? error.message : "Internal server error";
        response.status(500).json({ error: message });
    });
    return app;
}

Express API in this template:
- Register routes in `registerApis` (`backend/src/api/register.ts`); they are mounted before the `/api` 404
  fallback. The built server serves `frontend/dist` and the API on the same PORT.
- Sessions: an opaque random token stored server-side, sent as an `HttpOnly; SameSite=Lax; Path=/` cookie.
  Resolve the current user from the stored session on every request; never trust a user id sent by the client.
  Logout deletes the stored session and clears the cookie. An unknown token means signed out, not an error page.
- Each user sees and changes only their own records: filter by the session's user id in the SQL itself.
- Validation failures answer 4xx with a JSON message and change nothing; never answer 200 with an error body.
- Never return password hashes or session tokens in JSON.
- In the sandbox a server must listen on 0.0.0.0; declare its port in process_start and use ready_timeout.
- Check behavior with http_request (status, Set-Cookie, body) before relying on the browser.

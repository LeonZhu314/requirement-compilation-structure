React UI in this template (Vite, React 18, Tailwind available):
- Use the exact control names of the requirements as accessible names: `<a href="/login">Login</a>`,
  `<button>LOGIN</button>`, `<label>` bound to its input with `htmlFor`/`id` (or `aria-label`). Tests locate
  controls by role and exact name; a placeholder is not an accessible name.
- Native semantics first: links navigate (`<a href>`), actions are `<button>`, choices are `<select>`,
  radio groups are `role="radiogroup"` with an accessible name, errors use `role="alert"`.
- A password input has no textbox role: it is found by its label, so the label text must match exactly.
- Routes named by the requirements (`/`, `/login`, `/register`) must work on direct load and on refresh:
  the server already falls back to index.html; read `window.location.pathname` or use a router.
- Do not show cached identity before the session request finishes; render signed-out or a neutral state.
- After a successful mutation, update the visible state from the server response, then navigate if required.
- Disable or guard a submit button while its request is pending so one click sends one request.

import { useSyncExternalStore, type AnchorHTMLAttributes, type ReactNode } from "react";

// A small client router on the History API; the server already answers every
// non-API path with index.html, so each route is a real, reloadable URL.

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", listener);
  };
}

/** Go to another route of the application without reloading the page. */
export function navigate(to: string, options: { replace?: boolean } = {}) {
  if (options.replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  listeners.forEach(listener => listener());
  window.scrollTo(0, 0);
}

/** The current pathname; the component re-renders when it changes. */
export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}

/** A real <a href>: found as a link by its text, opened in a new tab normally, routed in place on a plain click. */
export function Link({ to, onClick, children, ...rest }:
    { to: string } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  return (
    <a {...rest} href={to} onClick={event => {
      onClick?.(event);
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey
          || event.altKey || rest.target) return;
      event.preventDefault();
      navigate(to);
    }}>{children}</a>
  );
}

export type RouteParams = Record<string, string>;

/** "/items/:id" against "/items/42" gives { id: "42" }; a final "*" accepts any remainder. */
export function matchPath(pattern: string, path: string): RouteParams | null {
  const expected = pattern.split("/").filter(Boolean);
  const actual = path.split("/").filter(Boolean);
  const params: RouteParams = {};
  for (let index = 0; index < expected.length; index += 1) {
    const part = expected[index];
    if (part === "*") return params;
    const value = actual[index];
    if (value === undefined) return null;
    if (part.startsWith(":")) params[part.slice(1)] = decodeURIComponent(value);
    else if (part !== value) return null;
  }
  return actual.length === expected.length ? params : null;
}

/** Render the first matching route: <Routes routes={{ "/": () => <Home />, "/items/:id": p => <Item id={p.id} /> }} /> */
export function Routes({ routes, fallback = null }:
    { routes: Record<string, (params: RouteParams) => ReactNode>; fallback?: ReactNode }) {
  const path = usePath();
  for (const [pattern, render] of Object.entries(routes)) {
    const params = matchPath(pattern, path);
    if (params) return <>{render(params)}</>;
  }
  return <>{fallback}</>;
}

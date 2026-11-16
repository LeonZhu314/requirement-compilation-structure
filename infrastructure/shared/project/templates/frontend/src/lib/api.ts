import { useCallback, useEffect, useState } from "react";

/** A non-2xx answer of the backend: its status, message and per-field messages. */
export class ApiError extends Error {
  readonly status: number;
  readonly fields: Record<string, string>;

  constructor(status: number, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.status = status;
    this.fields = fields;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const raw = await response.text();
  let data: unknown = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const record = (data !== null && typeof data === "object" ? data : {}) as { error?: unknown; fields?: unknown };
    throw new ApiError(response.status, typeof record.error === "string" ? record.error : `Request failed (${response.status})`,
      record.fields !== null && typeof record.fields === "object" ? (record.fields as Record<string, string>) : {});
  }
  return data as T;
}

/** JSON client for the same-origin API; the session cookie is sent automatically. */
export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

/** The message to show for any thrown value. */
export const errorMessage = (error: unknown) => (error instanceof Error ? error.message : "Something went wrong");

export interface Resource<T> {
  /** null until the first answer, and again after a failure: never a stale value. */
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Load a GET resource; `data` stays null while unresolved, so nothing cached is shown. */
export function useResource<T>(path: string | null): Resource<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>(
    { data: null, error: null, loading: path !== null });
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let current = true;
    setState(previous => ({ ...previous, loading: true }));
    api.get<T>(path).then(
      data => { if (current) setState({ data, error: null, loading: false }); },
      error => {
        if (current) setState({ data: null, loading: false,
          error: error instanceof ApiError ? error : new ApiError(0, errorMessage(error)) });
      });
    return () => { current = false; };
  }, [path, version]);
  const reload = useCallback(() => setVersion(value => value + 1), []);
  return { ...state, reload };
}

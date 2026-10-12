import type { FieldError } from "./types";

/** Single place that decides where the backend lives (same origin unless overridden). */
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number, public fields: FieldError[] = []) {
    super(message);
  }
}

function describe(detail: unknown): { message: string; fields: FieldError[] } {
  if (typeof detail === "string") return { message: detail, fields: [] };
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { message: string; errors?: FieldError[] };
    return { message: d.message, fields: d.errors ?? [] };
  }
  if (Array.isArray(detail)) {
    // FastAPI/pydantic validation errors
    const fields = detail.map((e: { loc?: unknown[]; msg?: string }) => ({
      field: String(e.loc?.[e.loc.length - 1] ?? ""), message: e.msg ?? "invalid value",
    }));
    return { message: fields.map((f) => f.message).join("; "), fields };
  }
  return { message: "Something went wrong", fields: [] };
}

/** Fired when a call comes back 401 so the app can show the login screen. */
export const UNAUTHORIZED_EVENT = "guardlens:unauthorized";
const AUTH_FORM_PATHS = ["/api/auth/login", "/api/auth/setup", "/api/auth/password"];

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const response = await fetch(API_BASE + path, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try { detail = (await response.json()).detail ?? detail; } catch { /* non-JSON error body */ }
    if (response.status === 401 && !AUTH_FORM_PATHS.includes(path)) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    const { message, fields } = describe(detail);
    throw new ApiError(message, response.status, fields);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

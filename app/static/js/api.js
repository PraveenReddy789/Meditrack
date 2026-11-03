// Thin fetch wrapper. Authentication is an HttpOnly cookie set by the server, so no
// token ever touches JavaScript; we only need to send same-origin credentials.

export class ApiError extends Error {
  constructor(status, message, items = []) {
    super(message);
    this.status = status;
    this.items = items; // [{loc: [...], msg}] for validation errors
  }
}

let unauthorizedHandler = () => {};
export function onUnauthorized(fn) {
  unauthorizedHandler = fn;
}

function describe(data) {
  if (!data || data.detail === undefined) return "Something went wrong. Please try again.";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((e) => `${fieldPath(e.loc)}${e.msg}`).join("; ");
  }
  return "Something went wrong. Please try again.";
}

export function fieldPath(loc = []) {
  const parts = loc.filter((p) => p !== "body" && p !== "appointments" && typeof p !== "number");
  return parts.length ? `${parts.join(".")}: ` : "";
}

export async function request(path, { method = "GET", body, signal } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return { res, data: null };

  const isCsv = (res.headers.get("content-type") || "").startsWith("text/csv");
  if (res.ok && isCsv) return { res, data: await res.blob() };

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/auth/login") unauthorizedHandler();
    throw new ApiError(res.status, describe(data), Array.isArray(data?.detail) ? data.detail : []);
  }
  return { res, data };
}

export async function api(path, options) {
  return (await request(path, options)).data;
}

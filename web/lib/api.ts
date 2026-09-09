/**
 * API client for the FitCoach gateway.
 *
 * Tokens are held in memory with the refresh token in localStorage. That is a
 * deliberate trade-off: an httpOnly cookie would be better against XSS, but
 * requires the API and client to share a domain, which this split deployment
 * does not. Documented in docs/security-review.md rather than left implicit.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const REFRESH_KEY = "fitcoach.refresh";

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setRefreshToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(REFRESH_KEY, token);
  else localStorage.removeItem(REFRESH_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function parseProblem(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail || body.title || `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  retryOnUnauthorised = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // Access tokens live 15 minutes, so a 401 mid-session is expected rather
  // than exceptional. One silent refresh keeps the user working.
  if (response.status === 401 && retryOnUnauthorised) {
    const refreshed = await tryRefresh();
    if (refreshed) return apiFetch<T>(path, options, false);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseProblem(response));
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export async function tryRefresh(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  try {
    const response = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!response.ok) {
      // A failed refresh means the token is revoked or expired. Clearing it
      // avoids a loop of doomed retries.
      setRefreshToken(null);
      setAccessToken(null);
      return false;
    }
    const data = await response.json();
    setAccessToken(data.access_token);
    setRefreshToken(data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

// --- Types ------------------------------------------------------------------

export interface UserProfile {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  timezone: string;
  weekly_digest: boolean;
}

export interface DecisionEvent {
  intent: string;
  decision: string;
  risk_score: number;
  policy_rule_id: string;
  reason_codes: string[];
  signal_contributions: Record<string, number>;
  extraction_confidence: number | null;
  pipeline_ms: number;
}

export interface Citation {
  source: string;
  snippet: string;
}

export interface WorkoutSet {
  exercise: string;
  load_kg: number | null;
  reps: number | null;
  sets: number | null;
  rpe: number | null;
  unit_original: string;
}

export interface WorkoutSession {
  session_date: string;
  message_id: string;
  sets: WorkoutSet[];
  tonnage_kg: number;
}

// --- Auth -------------------------------------------------------------------

export async function login(email: string, password: string) {
  const data = await apiFetch<{
    access_token: string;
    refresh_token: string;
  }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setAccessToken(data.access_token);
  setRefreshToken(data.refresh_token);
  return data;
}

export async function register(
  email: string,
  password: string,
  timezone: string,
) {
  return apiFetch<{ status: string; message: string }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, timezone }),
  });
}

export async function logout() {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } finally {
    setAccessToken(null);
    setRefreshToken(null);
  }
}

export const getProfile = () => apiFetch<UserProfile>("/api/auth/me");

export const getWorkouts = () =>
  apiFetch<{ sessions: WorkoutSession[]; count: number }>("/api/workouts");

export const getTelemetry = () =>
  apiFetch<{ quota: { used: number; limit: number; remaining: number } }>(
    "/api/telemetry",
  );

export const getExplanation = (messageId: string) =>
  apiFetch<{ message_id: string; trace: Record<string, unknown> }>(
    `/api/explain/${messageId}`,
  );

// --- Streaming chat ---------------------------------------------------------

export interface ChatHandlers {
  onStatus?: (data: Record<string, unknown>) => void;
  onDecision?: (data: DecisionEvent) => void;
  onMessage?: (text: string, citations: Citation[], terminal: boolean) => void;
  onDone?: (messageId: string) => void;
  onError?: (message: string) => void;
}

/**
 * Stream a chat turn over SSE.
 *
 * fetch with a ReadableStream is used rather than EventSource because
 * EventSource cannot set an Authorization header, and putting a bearer token
 * in a query string would leak it into server logs and browser history.
 */
export async function streamChat(message: string, handlers: ChatHandlers) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify({ message }),
  });

  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) return streamChat(message, handlers);
  }

  if (!response.ok || !response.body) {
    const detail = await parseProblem(response);
    if (response.status === 429) {
      const retryAfter = response.headers.get("Retry-After");
      handlers.onError?.(
        `${detail}${retryAfter ? ` Try again in ${retryAfter}s.` : ""}`,
      );
    } else {
      handlers.onError?.(detail);
    }
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Anything after the last
    // separator is a partial frame and stays in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) {
          eventName = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          switch (eventName) {
            case "status":
              handlers.onStatus?.(payload);
              break;
            case "decision":
              handlers.onDecision?.(payload as unknown as DecisionEvent);
              break;
            case "message":
              handlers.onMessage?.(
                String(payload.text ?? ""),
                (payload.citations as Citation[]) ?? [],
                Boolean(payload.terminal),
              );
              break;
            case "done":
              handlers.onDone?.(String(payload.message_id ?? ""));
              break;
            case "error":
              handlers.onError?.(
                String(payload.message ?? "Something failed."),
              );
              break;
          }
        }
      }
    }
  }
}

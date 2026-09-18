// Single typed entry point to the API. Nothing in the app calls fetch directly.
const BASE =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1"
    ? ""
    : "http://localhost:8000");

export type Band = "high" | "medium" | "review";

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ExtractedField {
  id: string;
  field_key: string;
  label: string;
  field_value: string | null;
  confidence: number | null;
  band: Band;
  source: "ai_extracted" | "user_entered" | "imported" | "system_derived";
  source_page: number | null;
  source_snippet: string | null;
  source_bbox: BBox | null;
  verification: "unverified" | "verified" | "disputed" | "rejected";
}

export interface DocumentRecord {
  id: string;
  title: string;
  category: string | null;
  status: string;
  page_count: number | null;
  fields: ExtractedField[];
}

export interface AssistantSource {
  ref: string;
  kind: "document" | "asset" | "property" | "deadline" | string;
  title: string;
  id: string;
  verification?: "verified" | "unverified" | "pending" | "n/a" | string;
}

export interface SuggestedAction {
  type: "upload_document" | "add_property" | "add_asset" | "consult_advisor" | string;
  label: string;
  action_url?: string | null;
  description?: string;
  note?: string;
}

export interface AssistantResponse {
  answer: string;
  refused: boolean;
  sources: AssistantSource[];
  suggested_action?: SuggestedAction | null;
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function token(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem("lao_token") ?? "demo_token_rahul_sharma";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, detail.detail ?? "Request failed.");
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  register: (body: { email: string; full_name: string; password: string }) =>
    request<{ access_token: string; family_id: string }>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; family_id: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  uploadDocument: (familyId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentRecord>(`/api/v1/families/${familyId}/documents`, {
      method: "POST",
      body: form,
    });
  },

  listDocuments: (familyId: string, status?: string) =>
    request<DocumentRecord[]>(
      `/api/v1/families/${familyId}/documents${status ? `?status=${status}` : ""}`,
    ),

  getDocument: (familyId: string, id: string) =>
    request<DocumentRecord>(`/api/v1/families/${familyId}/documents/${id}`),

  documentFileUrl: (familyId: string, id: string) =>
    request<{ url: string; expires_in: number }>(
      `/api/v1/families/${familyId}/documents/${id}/file`,
    ),

  documentPageUrl: (familyId: string, id: string, page: number) =>
    request<{ url: string; expires_in: number; page: number }>(
      `/api/v1/families/${familyId}/documents/${id}/pages/${page}`,
    ),

  verifyField: (familyId: string, docId: string, fieldId: string, value?: string) =>
    request<ExtractedField>(
      `/api/v1/families/${familyId}/documents/${docId}/fields/${fieldId}/verify`,
      { method: "POST", body: JSON.stringify({ value: value ?? null }) },
    ),

  deadlines: (familyId: string, withinDays = 90) =>
    request<
      { id: string; title: string; due_date: string; priority: string; days_left: number }[]
    >(`/api/v1/families/${familyId}/deadlines?within_days=${withinDays}`),

  ask: (familyId: string, question: string) =>
    request<AssistantResponse>(`/api/v1/families/${familyId}/assistant/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  streamAsk: async (
    familyId: string,
    question: string,
    callbacks: {
      onSources?: (
        sources: AssistantSource[],
        refused: boolean,
        suggestedAction?: SuggestedAction | null
      ) => void;
      onDelta?: (text: string) => void;
      onDone?: () => void;
      onError?: (err: Error) => void;
    },
    signal?: AbortSignal
  ): Promise<void> => {
    const headers = new Headers({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    });
    const t = token();
    if (t) headers.set("Authorization", `Bearer ${t}`);

    try {
      const res = await fetch(
        `${BASE}/api/v1/families/${familyId}/assistant/stream`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ question }),
          signal,
        }
      );

      if (!res.ok) {
        // Fallback to regular ask endpoint if streaming is not available
        const json = await api.ask(familyId, question);
        callbacks.onSources?.(json.sources, json.refused, json.suggested_action);
        callbacks.onDelta?.(json.answer);
        callbacks.onDone?.();
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("Streaming not supported by browser response body.");
      }

      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const block of lines) {
          if (!block.trim()) continue;
          let eventName = "message";
          let dataStr = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) {
              eventName = line.replace("event:", "").trim();
            } else if (line.startsWith("data:")) {
              dataStr += line.replace("data:", "").trim();
            }
          }

          if (eventName === "sources" && dataStr) {
            try {
              const payload = JSON.parse(dataStr);
              callbacks.onSources?.(
                payload.sources || [],
                Boolean(payload.refused),
                payload.suggested_action || null
              );
            } catch (e) {
              console.error("Failed to parse sources SSE", e);
            }
          } else if (eventName === "delta" && dataStr) {
            try {
              const payload = JSON.parse(dataStr);
              callbacks.onDelta?.(payload.text || "");
            } catch (e) {
              callbacks.onDelta?.(dataStr);
            }
          } else if (eventName === "done") {
            callbacks.onDone?.();
          }
        }
      }
      callbacks.onDone?.();
    } catch (err: any) {
      if (err.name === "AbortError") return;
      callbacks.onError?.(err);
    }
  },

  getGraph: (familyId: string) =>
    request<{
      nodes: { id: string; type: "person" | "asset" | "property"; label: string }[];
      edges: { from: string; to: string; label: string; verification?: "verified" | "unverified" }[];
    }>(`/api/v1/families/${familyId}/graph`),

  promoteDocument: (familyId: string, docId: string, target: "asset" | "property") =>
    request<{
      record_id: string;
      target: string;
      action: "created" | "updated";
      copied_fields: Record<string, string>;
      skipped_fields: { field_key: string; reason: string }[];
    }>(`/api/v1/families/${familyId}/documents/${docId}/promote`, {
      method: "POST",
      body: JSON.stringify({ target }),
    }),
};

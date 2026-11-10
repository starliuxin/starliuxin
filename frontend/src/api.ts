import type {
  Artifact,
  KnowledgeItem,
  Requirement,
  Run,
  RunEvent,
  Settings,
  SkillItem,
  StageId,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body && !isFormData ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (value: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(value),
});

export const api = {
  settings: () => request<Settings>("/api/settings"),
  runs: () => request<Run[]>("/api/runs"),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  createRun: (userInput: string, tokenBudget: number, externalModelAck: boolean) =>
    request<Run>(
      "/api/runs",
      json({
        user_input: userInput,
        token_budget: tokenBudget,
        external_model_ack: externalModelAck,
      }),
    ),
  artifacts: (id: string) => request<Artifact[]>(`/api/runs/${id}/artifacts`),
  requirements: (id: string) => request<Requirement[]>(`/api/runs/${id}/requirements`),
  updateRequirement: (runId: string, requirement: Requirement) =>
    request<Requirement>(`/api/runs/${runId}/requirements/${requirement.id}`, {
      method: "PUT",
      body: JSON.stringify({
        module: requirement.module,
        description: requirement.description,
        priority: requirement.priority,
        acceptance: requirement.acceptance,
        prototype_element: requirement.prototype_element,
      }),
    }),
  log: (id: string) => request<RunEvent[]>(`/api/runs/${id}/log`),
  resume: (
    id: string,
    decision: "continue" | "approve_review",
    comment = "",
    additionalTokenBudget = 0,
  ) =>
    request<Run>(
      `/api/runs/${id}/resume`,
      json({
        decision,
        comment,
        additional_token_budget: additionalTokenBudget,
      }),
    ),
  cancel: (id: string) => request<Run>(`/api/runs/${id}/cancel`, json({})),
  knowledge: () => request<KnowledgeItem[]>("/api/knowledge"),
  addKnowledge: (filename: string, content: string) =>
    request<KnowledgeItem>("/api/knowledge", json({ filename, content })),
  uploadKnowledge: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<KnowledgeItem>("/api/knowledge/upload", { method: "POST", body });
  },
  deleteKnowledge: (id: string) =>
    request<void>(`/api/knowledge/${id}`, { method: "DELETE" }),
  toggleKnowledge: (id: string, enabled: boolean) =>
    request<{ id: string; enabled: boolean }>(`/api/knowledge/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  skills: () => request<SkillItem[]>("/api/skills"),
  addSkill: (
    name: string,
    description: string,
    content: string,
    stages: StageId[],
  ) =>
    request<SkillItem>(
      "/api/skills",
      json({ name, description, content, stages, enabled: false }),
    ),
  toggleSkill: (id: string, enabled: boolean) =>
    request<{ id: string; enabled: boolean }>(`/api/skills/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
};

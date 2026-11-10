export type RunStatus =
  | "CREATED"
  | "PLANNING"
  | "RUNNING"
  | "WAITING_HUMAN"
  | "PAUSED"
  | "COMPLETED"
  | "CANCELLED"
  | "FAILED";

export type StageId = "S1" | "S2" | "S3" | "S4" | "S5" | "S6" | "S7" | "S8";

export interface Plan {
  final_goal: string;
  assumptions: string[];
  done_definition: string;
  steps: Array<{ id: string; stage: StageId; title: string; acceptance: string }>;
}

export interface Run {
  id: string;
  user_input: string;
  status: RunStatus;
  current_stage: StageId | null;
  token_budget: number;
  total_tokens: number;
  plan: Plan | null;
  error?: string;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: string;
  run_id: string;
  stage: string;
  version: number;
  kind: string;
  content: string;
  parent_version: number | null;
  created_at: string;
}

export interface Requirement {
  id: string;
  module: string;
  description: string;
  priority: "P0" | "P1" | "P2";
  acceptance: string;
  prototype_element: string;
  related_steps: string[];
  version: number;
  dirty: boolean;
}

export interface RunEvent {
  id: number;
  event_type: string;
  stage: StageId | null;
  message: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface KnowledgeItem {
  id: string;
  filename: string;
  file_type: string;
  source_metadata: KnowledgeSourceMetadata | null;
  enabled: number;
  created_at: string;
}

export interface KnowledgeSourceMetadata {
  sha256: string;
  source_size_bytes: number;
  extraction_method: string;
  extracted_bytes: number;
  page_count?: number;
  archive_entries?: number;
}

export interface SkillItem {
  id: string;
  name: string;
  description: string;
  stages: StageId[];
  enabled: number;
  created_at: string;
}

export interface Settings {
  provider: "demo" | "openai-compatible";
  model: string;
  external_data_disclosure: string | null;
  requires_token_budget: boolean;
  default_token_budget: null;
}

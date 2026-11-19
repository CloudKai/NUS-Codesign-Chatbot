import type { Citation } from './stream';

/** Public reader contracts. Credentials stay in HttpOnly same-origin cookies. */
export interface Session { owner_id: string; display_name: string; kind: 'guest' | 'registered' }
export interface Notebook { id: string; name: string; kind: 'notebook' | 'chat'; parent_notebook_id: string | null; pinned: boolean }
export interface Message { id: string; role: string; content: string; citations: Citation[]; feedback_available: boolean; rating: 'useful' | 'not_useful' | null }
export interface ChatSummary { preview: string; activity_at: string }
export interface NotebookList { owner_id: string; notebooks: Notebook[]; chat_summaries: Record<string, ChatSummary> }
export interface Page {
  owner_id: string; notebook: Notebook; messages: Message[];
  next_cursor: string | null; total_count: number; conversation_revision: number;
}

/** HTTP status supports fixed recovery copy without echoing private server errors. */
export class ApiError extends Error {
  constructor(public status: number) { super('Reader request failed'); }
}

/** Signal that the signed-in account belongs in the protected workspace. */
export class StreamlitAccess extends Error {}

/** Fetch JSON without retaining private browser HTTP cache entries. */
export async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok) throw new ApiError(response.status);
  return await response.json() as T;
}

/** Probe the owner, refreshing registered cookies through the existing auth route if needed. */
export async function currentSession(signal: AbortSignal): Promise<Session> {
  try { return await get<Session>('/api/v1/reader/session', signal); }
  catch (error) {
    if (!(error instanceof ApiError) || ![401, 403].includes(error.status)) throw error;
    const profile = await get<{ user: { streamlit_access: boolean } }>('/api/v1/auth/me', signal);
    if (profile.user.streamlit_access) throw new StreamlitAccess();
    if (error.status === 403) throw error;
    return get<Session>('/api/v1/reader/session', signal);
  }
}

/** Saved project artifacts and navigation are projected by the shared learning policy. */
export interface Stage {
  id: string; label: string; completed: boolean; selectable: boolean;
  artifact_label: string; student_work: { message_id: string; text: string }[];
  feedback: { message_id: string; text: string }[]; coach_summary: string;
  decision: string; next_action: string;
}
export interface Project {
  owner_id: string; thread_id: string; current_stage: string; stages: Stage[];
  pending: { id: string; from_stage: string; to_stage: string; rationale: string } | null;
  review?: {
    summary: string;
    strengths: ReviewFeedback[];
    improvements: ReviewFeedback[];
    facione_scores: { dimension: string; score: number | null }[];
  };
}
export interface ReviewFeedback { stage_id: string; items: string[] }

/** Allowlisted notebook controls; all educational state remains server-owned. */
export interface NotebookSettings {
  owner_id: string; notebook: Notebook; response_detail: 'short' | 'long'; response_language: string;
  selected_model: string; reasoning_effort: string | null; assignment: Record<string, string>;
  models: { id: string; label: string; reasoning_efforts: string[] }[];
}
export interface Preferences {
  owner_id: string;
  appearance: 'System' | 'Light' | 'Dark';
  display_name: string;
  reduce_motion: boolean;
  default_mode: 'lecture' | 'project';
  starter_prompts: boolean;
}

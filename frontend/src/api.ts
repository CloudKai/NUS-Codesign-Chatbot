import type { Citation } from './stream';
import { ApiError } from './api/errors';
import { readBootstrap, readSession } from './api/client';
import type { ReaderSession, ReaderNotebook, ReaderChatSummary, ReaderNotebooks } from './api/generated/types.gen';
export { ApiError } from './api/errors';

/** Public reader contracts. Credentials stay in HttpOnly same-origin cookies. */
export type Session = ReaderSession;
export type Notebook = Required<ReaderNotebook>;
export interface Message { id: string; role: string; content: string; citations: Citation[]; starred: boolean; feedback_available: boolean; rating: 'useful' | 'not_useful' | null }
export type ChatSummary = ReaderChatSummary;
export type NotebookList = Omit<ReaderNotebooks, 'notebooks'> & { notebooks: Notebook[] };
export interface Page {
  owner_id: string; notebook: Notebook; messages: Message[];
  next_cursor: string | null; total_count: number; conversation_revision: number;
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
  try { return await readSession(signal); }
  catch (error) {
    if (!(error instanceof ApiError) || ![401, 403].includes(error.status)) throw error;
    const profile = await get<{ user: { streamlit_access: boolean } }>('/api/v1/auth/me', signal);
    if (profile.user.streamlit_access) throw new StreamlitAccess();
    if (error.status === 403) throw error;
    return readSession(signal);
  }
}

/** Renew expired cookies if needed, then fence the whole bootstrap with a fresh owner probe. */
export async function verifiedBootstrap(signal: AbortSignal): Promise<Awaited<ReturnType<typeof readBootstrap>>> {
  let value;
  try { value = await readBootstrap(signal); }
  catch (error) {
    if (!(error instanceof ApiError) || ![401, 403].includes(error.status)) throw error;
    await currentSession(signal);
    value = await readBootstrap(signal);
  }
  const verified = await currentSession(signal);
  if (verified.owner_id !== value.session.owner_id || value.listing.owner_id !== verified.owner_id
    || value.preferences.owner_id !== verified.owner_id) throw new ApiError(401);
  return { ...value, session: verified };
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
    project_brief?: ProjectBriefResult;
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
  chat_model_label?: string;
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

/** Owner/revision-fenced bookmarks load independently from transcript pagination. */
export interface Bookmark { id: string; role: 'user' | 'assistant'; preview: string; stage_id: string | null; interaction_intent: 'lecture_help' | 'project_coaching' | null }
export interface Bookmarks { owner_id: string; thread_id: string; conversation_revision: number; messages: Bookmark[] }

/** Whole-active-chat project synthesis, grounded in saved student statements. */
export interface ProjectBriefPoint { text: string | null; evidence: string[] }
export interface ProjectBriefResult {
  status: 'current' | 'missing' | 'empty' | 'preview' | 'failed'; version: string;
  brief: { who_and_why: ProjectBriefPoint; problem: ProjectBriefPoint; current_idea: ProjectBriefPoint; what_matters: ProjectBriefPoint; still_to_explore: ProjectBriefPoint } | null;
}

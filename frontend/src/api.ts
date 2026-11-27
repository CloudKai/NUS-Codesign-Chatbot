import type { Citation } from './stream';
import { ApiError } from './api/errors';
import { readBootstrap, readSession } from './api/client';
import type { ReaderSession, ReaderNotebook, ReaderChatSummary, ReaderNotebooks } from './api/generated/types.gen';
export { ApiError } from './api/errors';

/** Public reader contracts. Credentials stay in HttpOnly same-origin cookies. */
export type Session = ReaderSession;
export type Notebook = Required<ReaderNotebook>;
export interface Message { id: string; role: string; content: string; interaction_intent?: Bookmark['interaction_intent']; citations: Citation[]; canvas_suggestions?: CanvasSuggestion[]; artifact_feedback?: ArtifactFeedback[]; canvas_draft?: CanvasDraft | null; starred: boolean; feedback_available: boolean; rating: 'useful' | 'not_useful' | null }

/** One inert structured canvas proposal saved with an assistant answer.
 * The student must explicitly accept it; acceptance runs the ordinary
 * revision-guarded canvas save and nothing applies automatically. */
export interface CanvasSuggestion {
  id: string; kind: 'new_node' | 'new_edge'; node_kind?: string | null; title?: string;
  description?: string; relation?: string | null; source_node_id?: string | null;
  target_node_id?: string | null; explanation?: string | null; rationale: string;
  base_canvas_id?: string | null; base_canvas_revision?: number | null;
}

/** One reviewable synthesized draft from the student's selected canvas nodes.
 * The student edits and confirms it; confirmation always creates a new artifact. */
export interface CanvasDraft {
  id: string; title: string; draft_text: string; rationale?: string;
  base_canvas_id?: string | null; base_canvas_revision?: number | null;
  node_ids?: string[]; provenance?: 'coach';
}

/** One inert before/after artifact feedback pair saved with an assistant answer.
 * The student inspects both sides and only explicit acceptance — the ordinary
 * revision-guarded artifact save — changes the document. */
export interface ArtifactFeedback {
  id: string; kind: 'revise_text'; proposed_text: string; rationale: string;
  base_artifact_id?: string | null; base_artifact_revision?: number | null;
  paragraph?: number | null; original_text?: string;
}
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

/** Saved project artifacts and navigation are projected by the shared learning policy. */export interface Stage {
  id: string; label: string; completed: boolean; selectable: boolean;
  artifact_label: string; student_work: { message_id: string; text: string }[];
  feedback: { message_id: string; text: string }[]; coach_summary: string;
  decision: string; next_action: string; criteria: string[];
}
export interface Project {
  owner_id: string; thread_id: string; current_stage: string; stages: Stage[];
  pending: { id: string; from_stage: string; to_stage: string; rationale: string } | null;
  recaps?: MilestoneRecapView[];
  review?: {
    project_brief?: ProjectBriefResult;
    summary: string;
    strengths: ReviewFeedback[];
    improvements: ReviewFeedback[];
    facione_scores: { dimension: string; score: number | null }[];
  };
}
export interface ReviewFeedback { stage_id: string; items: string[] }
/** One persisted confirmed-milestone recap; read-only history with no stage authority. */
export interface MilestoneRecapView {
  id: string; stage_id: string; stage_label: string; transition_id: string;
  next_stage_id: string; next_stage_label: string; next_action: string;
  accomplishments: string; changes: string; gaps: string[];
  relevant_work: { message_id: string; preview: string }[];
  confirmed_at: string;
}

/** Allowlisted notebook controls; all educational state remains server-owned. */
export interface NotebookSettings {
  owner_id: string; notebook: Notebook; response_detail: 'short' | 'long'; response_language: string;
  chat_model_label?: string;
  selected_model: string; reasoning_effort: string | null; assignment: Record<string, string>;
  models: { id: string; label: string; reasoning_efforts: string[] }[];
}

/** Supplied notebook controls; omitted keys keep their saved values. */
export interface NotebookSettingsPatch {
  name?: string; pinned?: boolean; response_detail?: 'short' | 'long'; response_language?: string;
  selected_model?: string; reasoning_effort?: string | null; assignment?: Record<string, string>;
}
export interface Preferences {
  owner_id: string;
  appearance: 'System' | 'Light' | 'Dark';
  display_name: string;
  reduce_motion: boolean;
  default_mode: 'improve' | 'project';
  starter_prompts: boolean;
}

/** Owner/revision-fenced bookmarks load independently from transcript pagination. */
export interface Bookmark { id: string; role: 'user' | 'assistant'; preview: string; stage_id: string | null; interaction_intent: 'lecture_help' | 'improve_design' | 'project_coaching' | null }
export interface Bookmarks { owner_id: string; thread_id: string; conversation_revision: number; messages: Bookmark[] }

/** One bounded owner-consistent workspace open read; not a transactional snapshot. */
export interface ThreadWorkspace {
  owner_id: string; page: Page; project: Project; bookmarks: Bookmarks; settings: NotebookSettings;
}

/** Owner-scoped source metadata; storage keys and extracted content stay private. */
export interface Source { id: string; title: string; selected: boolean; locked: boolean; kind: string; size: number }
export interface SourceList { owner_id: string; thread_id: string; sources: Source[]; max_files: number; max_file_bytes: number }
export interface SourceDetail { source: Source; text: string; truncated: boolean }
export interface UploadJob { id: string; filenames: string[]; state: 'queued' | 'processing' | 'saved' | 'failed'; retryable: boolean }
export interface UploadJobs { owner_id: string; thread_id: string; jobs: UploadJob[] }

/** Persistent student artifact: canonical Tiptap document with revision-guarded saves. */
export const ARTIFACT_KINDS = ['notes', 'problem_identification', 'concept_generation',
  'design_specification', 'ethics_critical_thinking', 'reflection'] as const;
export type ArtifactKind = (typeof ARTIFACT_KINDS)[number];
export type ArtifactDocument = { type: 'doc'; content: unknown[] };
export interface Artifact {
  owner_id: string; thread_id: string; id: string; title: string; kind: string; document: ArtifactDocument;
  schema_version: number; revision: number; origin: string; created_at: string; updated_at: string;
  references: EvidenceReference[];
}
/** One resolved evidence link: unavailable/stale stays explicit, never substituted. */
export interface EvidenceReference {
  kind: 'source' | 'message' | 'artifact' | 'canvas_node'; id: string;
  canvas_id?: string; available?: boolean; title?: string | null;
  /** The saved artifact version or canvas revision linked content came from. */
  revision?: number;
}
export interface ArtifactSummaries {
  owner_id: string; thread_id: string; kinds: readonly string[];
  artifacts: Omit<Artifact, 'document' | 'owner_id' | 'references'>[];
}
export interface ArtifactVersionSummary {
  revision: number; title: string; kind: string; origin: string;
  restored_from: number | null; created_at: string;
}
export interface ArtifactVersions {
  owner_id: string; thread_id: string; artifact_id: string; versions: ArtifactVersionSummary[];
}
export interface ArtifactVersion extends ArtifactVersionSummary {
  owner_id: string; thread_id: string; artifact_id: string; document: ArtifactDocument;
}

/** Persistent design canvas: a validated node/relationship graph with revision-guarded saves. */
export const CANVAS_NODE_KINDS = ['note', 'problem', 'stakeholder', 'need', 'evidence', 'assumption',
  'constraint', 'concept', 'specification', 'ethics', 'evaluation', 'reflection'] as const;
export const CANVAS_RELATIONS = ['supports', 'addresses', 'depends_on', 'conflicts_with', 'requires',
  'derived_from', 'alternative_to', 'evaluated_against', 'raises_concern'] as const;
/** The persisted Thinking Path stage ids a node may optionally associate with. */
export const CANVAS_STAGE_IDS = ['problem_identification', 'concept_generation',
  'design_specification', 'ethics_critical_thinking', 'reflection'] as const;
export const CANVAS_STAGE_LABELS: Record<CanvasStageId, string> = {
  problem_identification: 'Problem identification',
  concept_generation: 'Concept generation',
  design_specification: 'Design specification',
  ethics_critical_thinking: 'Ethics & critical thinking',
  reflection: 'Reflection',
};
export type CanvasNodeKind = (typeof CANVAS_NODE_KINDS)[number];
export type CanvasRelation = (typeof CANVAS_RELATIONS)[number];
export type CanvasStageId = (typeof CANVAS_STAGE_IDS)[number];
export interface CanvasNode {
  id: string; kind: CanvasNodeKind; title: string; description: string; x: number; y: number;
  stage?: CanvasStageId; references?: EvidenceReference[];
}
export interface CanvasEdge {
  id: string; source: string; target: string; relation: CanvasRelation; explanation: string;
}
export interface CanvasGraph {
  nodes: CanvasNode[]; edges: CanvasEdge[];
  accepted_suggestion_ids?: string[];
}
export interface Canvas {
  owner_id: string; thread_id: string; id: string; title: string; graph: CanvasGraph;
  schema_version: number; revision: number; origin: string; created_at: string; updated_at: string;
}
export interface CanvasSummaries {
  owner_id: string; thread_id: string; node_kinds: readonly string[]; relations: readonly string[];
  stages: readonly string[];
  canvases: Omit<Canvas, 'graph' | 'owner_id'>[];
}
export interface CanvasVersionSummary {
  revision: number; title: string; origin: string;
  restored_from: number | null; created_at: string;
}
export interface CanvasVersions {
  owner_id: string; thread_id: string; canvas_id: string; versions: CanvasVersionSummary[];
}
export interface CanvasVersion extends CanvasVersionSummary {
  owner_id: string; thread_id: string; canvas_id: string; graph: CanvasGraph;
}

/** Whole-active-chat project synthesis, grounded in saved student statements. */
export interface ProjectBriefPoint { text: string | null; evidence: string[] }
export interface ProjectBriefResult {
  status: 'current' | 'missing' | 'empty' | 'preview' | 'failed'; version: string;
  brief: { who_and_why: ProjectBriefPoint; problem: ProjectBriefPoint; current_idea: ProjectBriefPoint; what_matters: ProjectBriefPoint; still_to_explore: ProjectBriefPoint } | null;
}

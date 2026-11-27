/** Reviewed generated reads with the existing cookie, cancellation and privacy policy. */
import { createClient } from './generated/client';
import {
  readerArtifact, readerArtifactCreate, readerArtifactDelete, readerArtifactDuplicate,
  readerArtifactUpdate, readerArtifacts, readerArtifactVersion, readerArtifactVersions,
  readerArtifactRestore,
  readerBookmarks, readerBootstrap, readerCanvas, readerCanvasCreate, readerCanvasDelete, readerCanvasUpdate,
  readerCanvases, readerCanvasVersion, readerCanvasVersions, readerCanvasRestore,
  readerDeepReview, readerDeepReviewCancel, readerDeepReviewStart,
  readerMessages, readerNotebookSettings, readerNotebooks,
  readerNotebookSettingsUpdate, readerPreferences, readerPreferencesUpdate, readerProject,
  readerProjectBrief, readerProjectResolve, readerProjectSelect, readerSession,
  readerSource, readerSourceLink, readerSourceRemove, readerSourceSelect, readerSources,
  readerStar, readerThreadMove, readerThreadRemove, readerThreadsCreate, readerThreadWorkspace,
  readerUploadDiscard, readerUploadRetry, readerUploads,
} from './generated/sdk.gen';
import type { ProjectBriefResult as GeneratedProjectBriefResult, ReaderArtifact as GeneratedReaderArtifact, ReaderCanvas as GeneratedReaderCanvas, ReaderNotebook, ReaderPage, ReaderProject, ReaderRemoved, ReaderThreadWorkspace } from './generated/types.gen';
import type { ReaderBootstrap } from './generated/types.gen';
import type { Artifact, ArtifactDocument, ArtifactSummaries, ArtifactVersion, ArtifactVersions, Bookmarks, Canvas, CanvasGraph, CanvasSummaries, CanvasVersion, CanvasVersions, EvidenceReference, MilestoneRecapView, Notebook, NotebookList, NotebookSettings, NotebookSettingsPatch, Page, Preferences, Project, ProjectBriefResult, Session, SourceDetail, SourceList, ThreadWorkspace, UploadJobs } from '../api';
import { ApiError } from './errors';

export const browserClient = createClient({ credentials: 'same-origin', cache: 'no-store', baseUrl: '' });

/** Keep transport failures (including abort) distinct from HTTP status failures. */
function confirmed<T>(result: { data?: T; error?: unknown; response?: Response }): T {
  if (result.response && !result.response.ok) throw new ApiError(result.response.status);
  if (result.data === undefined) throw result.error ?? new Error('Reader response missing');
  return result.data;
}

/** Materialize documented server defaults while preserving the legacy view shape. */
function notebook(value: ReaderNotebook): Notebook {
  return { ...value, kind: value.kind ?? 'chat', parent_notebook_id: value.parent_notebook_id ?? null, pinned: value.pinned ?? false };
}

/** Fetch initial owner-bound projections without triggering any model operation. */
export async function readBootstrap(signal: AbortSignal): Promise<Omit<ReaderBootstrap, 'listing'> & { listing: NotebookList }> {
  const value = confirmed(await readerBootstrap({ client: browserClient, signal }));
  return { ...value, listing: { ...value.listing, notebooks: value.listing.notebooks.map(notebook) } };
}

/** Read the verified identity without changing cookie renewal behavior. */
export async function readSession(signal: AbortSignal): Promise<Session> {
  return confirmed(await readerSession({ client: browserClient, signal }));
}

/** Fetch owned sidebar metadata through the generated read operation. */
export async function readNotebookList(signal: AbortSignal): Promise<NotebookList> {
  const list = confirmed(await readerNotebooks({ client: browserClient, signal }));
  return { ...list, notebooks: list.notebooks.map(notebook) };
}

/** Materialize documented server defaults for one revision-bound transcript page. */
function pageView(value: ReaderPage): Page {
  return { ...value, notebook: notebook(value.notebook), messages: value.messages.map(message => ({
    ...message, starred: message.starred ?? false, feedback_available: message.feedback_available ?? false,
    rating: message.rating ?? null,
    canvas_suggestions: message.canvas_suggestions ?? [],
    artifact_feedback: message.artifact_feedback ?? [],
    canvas_draft: message.canvas_draft ?? null,
    citations: (message.citations ?? []).map(citation => ({ ...citation, excerpt: citation.excerpt ?? '' })),
  })) };
}

/** Fetch one revision-bound page; pagination and request ownership remain server-owned. */
export async function readMessagePage(thread: string, signal: AbortSignal, cursor?: string | null, limit = 20): Promise<Page> {
  const value = confirmed(await readerMessages({ client: browserClient, signal,
    path: { thread_id: thread }, query: { limit, ...(cursor ? { cursor } : {}) } }));
  return pageView(value);
}

/** Materialize documented server defaults for one whole-chat brief envelope. */
function briefView(value: GeneratedProjectBriefResult): ProjectBriefResult {
  const brief = value.brief;
  const point = (input: { text?: string | null; evidence?: string[] } | undefined) =>
    ({ text: input?.text ?? null, evidence: input?.evidence ?? [] });
  return {
    status: value.status,
    version: value.version ?? '',
    brief: brief ? {
      who_and_why: point(brief.who_and_why),
      problem: point(brief.problem),
      current_idea: point(brief.current_idea),
      what_matters: point(brief.what_matters),
      still_to_explore: point(brief.still_to_explore),
    } : null,
  };
}

/** Materialize documented server defaults for one saved project projection. */
/** Materialize documented server defaults for one saved milestone recap. */
/** Materialize documented server defaults for one saved milestone recap. */
function recapView(value: NonNullable<ReaderProject['recaps']>[number]): MilestoneRecapView {
  return {
    ...value,
    accomplishments: value.accomplishments ?? '',
    changes: value.changes ?? '',
    gaps: value.gaps ?? [],
    relevant_work: value.relevant_work ?? [],
  };
}

function projectView(value: ReaderProject): Project {
  const saved = value.review.project_brief;
  return {
    ...value,
    recaps: (value.recaps ?? []).map(recapView),
    stages: value.stages.map(stage => ({
      ...stage,
      coach_summary: stage.coach_summary ?? '',
      decision: stage.decision ?? '',
      criteria: stage.criteria ?? [],
      feedback: stage.feedback ?? [],
      student_work: stage.student_work ?? [],
    })),
    review: {
      ...value.review,
      project_brief: briefView(saved),
    },
  };
}

/** Read one bounded owner-consistent workspace open projection set. */
export async function readThreadWorkspace(thread: string, signal: AbortSignal): Promise<ThreadWorkspace> {
  const value: ReaderThreadWorkspace = confirmed(await readerThreadWorkspace({ client: browserClient, signal,
    path: { thread_id: thread } }));
  return {
    owner_id: value.owner_id,
    page: pageView(value.page),
    project: projectView(value.project),
    bookmarks: value.bookmarks,
    settings: { ...value.settings, notebook: notebook(value.settings.notebook) },
  };
}

/** Read the verified owner's presentation defaults through the generated operation. */
export async function readPreferences(signal: AbortSignal): Promise<Preferences> {
  return confirmed(await readerPreferences({ client: browserClient, signal }));
}

/** Merge supplied preference keys and return the owner-fenced saved result. */
export async function updatePreferences(patch: Partial<Omit<Preferences, 'owner_id'>>, signal: AbortSignal): Promise<Preferences> {
  return confirmed(await readerPreferencesUpdate({ client: browserClient, signal, body: patch }));
}

/** Read one notebook's owner-fenced action projection through the generated operation. */
export async function readNotebookSettings(thread: string, signal: AbortSignal): Promise<NotebookSettings> {
  const value = confirmed(await readerNotebookSettings({ client: browserClient, signal, path: { thread_id: thread } }));
  return { ...value, notebook: notebook(value.notebook) };
}

/** Save supplied notebook controls and return the owner-fenced saved projection. */
export async function updateNotebookSettings(
  thread: string, patch: NotebookSettingsPatch, signal: AbortSignal,
): Promise<NotebookSettings> {
  const value = confirmed(await readerNotebookSettingsUpdate({ client: browserClient, signal,
    path: { thread_id: thread }, body: patch }));
  return { ...value, notebook: notebook(value.notebook) };
}

/** Create an owned notebook or quick chat and return its owner-fenced action projection. */
export async function createThread(
  body: { name: string } | { kind: 'chat'; parent_notebook_id?: string | null }, signal: AbortSignal,
): Promise<NotebookSettings> {
  const value = confirmed(await readerThreadsCreate({ client: browserClient, signal,
    body: body as { name?: string; kind?: 'chat'; parent_notebook_id?: string | null } }));
  return { ...value, notebook: notebook(value.notebook) };
}

/** Save an owner-validated chat location and return the confirmed projection. */
export async function moveThread(
  thread: string, parentNotebookId: string | null, signal: AbortSignal,
): Promise<NotebookSettings> {
  const value = confirmed(await readerThreadMove({ client: browserClient, signal,
    path: { thread_id: thread }, body: { parent_notebook_id: parentNotebookId } }));
  return { ...value, notebook: notebook(value.notebook) };
}

/** Delete one confirmed owned thread and return the owner-fenced receipt. */
export async function removeThread(thread: string, signal: AbortSignal): Promise<ReaderRemoved> {
  return confirmed(await readerThreadRemove({ client: browserClient, signal,
    path: { thread_id: thread }, body: { confirmed: true } }));
}

/** Read one owner/notebook-fenced source catalog; thread "library" lists the private Library. */
export async function readSources(thread: string, signal: AbortSignal): Promise<SourceList> {
  return confirmed(await readerSources({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Read one owned source's bounded extracted-text preview. */
export async function readSourceDetail(thread: string, sourceId: string, signal: AbortSignal): Promise<SourceDetail> {
  return confirmed(await readerSource({ client: browserClient, signal,
    path: { thread_id: thread, source_id: sourceId } }));
}

/** Read one owner/notebook-fenced upload receipt set. */
export async function readUploads(thread: string, signal: AbortSignal): Promise<UploadJobs> {
  return confirmed(await readerUploads({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Save an explicit selection and return the confirmed owner-fenced catalog. */
export async function setSourceSelected(
  thread: string, sourceId: string, selected: boolean, signal: AbortSignal,
): Promise<SourceList> {
  return confirmed(await readerSourceSelect({ client: browserClient, signal,
    path: { thread_id: thread, source_id: sourceId }, body: { selected } }));
}

/** Add an owned Library source to the target notebook and enable it. */
export async function linkLibrarySource(thread: string, sourceId: string, signal: AbortSignal): Promise<SourceList> {
  return confirmed(await readerSourceLink({ client: browserClient, signal,
    path: { thread_id: thread, source_id: sourceId } }));
}

/** Detach a notebook source, or permanently delete an explicitly confirmed Library original. */
export async function removeSource(
  thread: string, sourceId: string, signal: AbortSignal, confirmDeletion?: boolean,
): Promise<SourceList> {
  return confirmed(await readerSourceRemove({ client: browserClient, signal,
    path: { thread_id: thread, source_id: sourceId }, body: confirmDeletion ? { confirmed: true } : undefined }));
}

/** Queue a retry of one owned retained upload failure. */
export async function retryUpload(
  thread: string, uploadId: string, signal: AbortSignal,
): Promise<Record<string, boolean>> {
  return confirmed(await readerUploadRetry({ client: browserClient, signal,
    path: { thread_id: thread, upload_id: uploadId } }));
}

/** Release one terminal owned upload receipt or failure. */
export async function discardUpload(
  thread: string, uploadId: string, signal: AbortSignal,
): Promise<Record<string, boolean>> {
  return confirmed(await readerUploadDiscard({ client: browserClient, signal,
    path: { thread_id: thread, upload_id: uploadId } }));
}

/** Read one owner/revision-fenced bookmark projection, independent of transcript pagination. */
export async function readBookmarks(thread: string, signal: AbortSignal): Promise<Bookmarks> {
  return confirmed(await readerBookmarks({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Save one explicit star state on an owned active message. */
export async function setStar(
  thread: string, messageId: string, starred: boolean, signal: AbortSignal,
): Promise<{ starred: boolean }> {
  return confirmed(await readerStar({ client: browserClient, signal,
    path: { thread_id: thread, message_id: messageId }, body: { starred } }));
}

/** Read one owner-fenced project projection with its Thinking Path navigation. */
export async function readProject(thread: string, signal: AbortSignal): Promise<Project> {
  return projectView(confirmed(await readerProject({ client: browserClient, signal, path: { thread_id: thread } })));
}

/** Apply one explicit transition decision exactly once and return the confirmed project. */
export async function resolveTransition(
  thread: string, transitionId: string, accepted: boolean, signal: AbortSignal,
): Promise<Project> {
  return projectView(confirmed(await readerProjectResolve({ client: browserClient, signal,
    path: { thread_id: thread, transition_id: transitionId }, body: { accepted } })));
}

/** Select one application-authorized stage and return the confirmed project. */
export async function selectStage(thread: string, stageId: string, signal: AbortSignal): Promise<Project> {
  return projectView(confirmed(await readerProjectSelect({ client: browserClient, signal,
    path: { thread_id: thread }, body: { stage_id: stageId } })));
}

/** Request one explicit whole-chat summary (or its retry) and return the saved state. */
export async function requestProjectBrief(thread: string, retry: boolean, signal: AbortSignal): Promise<ProjectBriefResult> {
  return briefView(confirmed(await readerProjectBrief({ client: browserClient, signal,
    path: { thread_id: thread }, body: { retry } })));
}

/** Read one owned notebook's artifact list without document bodies. */
export async function readArtifacts(thread: string, signal: AbortSignal): Promise<ArtifactSummaries> {
  return confirmed(await readerArtifacts({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Create one owned persistent artifact and return its owner-fenced projection. */
export async function createArtifact(thread: string, title: string, document: ArtifactDocument,
                                     signal: AbortSignal, kind: string = 'notes',
                                     references?: EvidenceReference[], requestId?: string,
                                     origin?: string): Promise<Artifact> {
  const created = confirmed(await readerArtifactCreate({ client: browserClient, signal,
    path: { thread_id: thread },
    body: { title, kind, document,
      ...(references?.length ? { references: references as unknown as { [key: string]: unknown }[] } : {}),
      ...(requestId ? { request_id: requestId } : {}),
      ...(origin ? { origin } : {}) } }));
  return artifactView(created);
}

/** Copy one owned artifact with its kind, title and canonical document. */
export async function duplicateArtifact(thread: string, artifactId: string,
                                        signal: AbortSignal): Promise<Artifact> {
  return artifactView(confirmed(await readerArtifactDuplicate({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId } })));
}

/** Delete one owned artifact after an explicit confirmation; returns the removed identity. */
export async function deleteArtifact(thread: string, artifactId: string,
                                     signal: AbortSignal): Promise<{ id: string; title: string }> {
  const removed = confirmed(await readerArtifactDelete({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId }, body: { confirmed: true } }));
  return { id: removed.id, title: removed.title };
}

/** Read one owned artifact with its canonical document. */
export async function readArtifact(thread: string, artifactId: string, signal: AbortSignal): Promise<Artifact> {
  return artifactView(confirmed(await readerArtifact({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId } })));
}

/** Materialize the typed canonical document the server validated before storage. */
function artifactView(value: GeneratedReaderArtifact): Artifact {
  const raw = value.document as { type?: unknown; content?: unknown };
  if (raw.type !== 'doc' || !Array.isArray(raw.content)) throw new ApiError(502);
  return { ...value, document: { type: 'doc', content: raw.content },
    references: (value.references ?? []) as unknown as Artifact['references'] };
}

/** Materialize one version preview's canonical document. */
function artifactVersionView(value: {
  owner_id: string; thread_id: string; artifact_id: string; revision: number; title: string;
  kind: string; document: { [key: string]: unknown }; origin: string;
  restored_from: number | null; created_at: string;
}): ArtifactVersion {
  const raw = value.document as { type?: unknown; content?: unknown };
  if (raw.type !== 'doc' || !Array.isArray(raw.content)) throw new ApiError(502);
  return { ...value, document: { type: 'doc', content: raw.content } };
}

/** Apply one explicit revision-guarded save and return the confirmed artifact. */
export async function saveArtifact(thread: string, artifactId: string, document: ArtifactDocument,
                                   revision: number, title: string | null, signal: AbortSignal,
                                   references?: EvidenceReference[] | null): Promise<Artifact> {
  const saved = confirmed(await readerArtifactUpdate({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId },
    body: { document, revision, ...(title !== null ? { title } : {}),
      ...(references ? { references: references as unknown as { [key: string]: unknown }[] } : {}) } }));
  return artifactView(saved);
}

/** Read one owned artifact's bounded version history without document bodies. */
export async function readArtifactVersions(thread: string, artifactId: string,
                                           signal: AbortSignal): Promise<ArtifactVersions> {
  return confirmed(await readerArtifactVersions({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId } }));
}

/** Read one owned version's readable preview. */
export async function readArtifactVersion(thread: string, artifactId: string, revision: number,
                                          signal: AbortSignal): Promise<ArtifactVersion> {
  return artifactVersionView(confirmed(await readerArtifactVersion({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId, revision } })));
}

/** Restore an older version as a new revision guarded by the seen one. */
export async function restoreArtifactVersion(thread: string, artifactId: string, versionRevision: number,
                                             seenRevision: number, signal: AbortSignal): Promise<Artifact> {
  return artifactView(confirmed(await readerArtifactRestore({ client: browserClient, signal,
    path: { thread_id: thread, artifact_id: artifactId, revision: versionRevision },
    body: { revision: seenRevision } })));
}

/** Materialize the typed canonical graph the server validated before storage. */
function canvasView(value: GeneratedReaderCanvas): Canvas {
  const graph = value.graph as {
    nodes?: unknown; edges?: unknown; accepted_suggestion_ids?: unknown };
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new ApiError(502);
  // Acceptance provenance must survive the projection so other sessions do
  // not re-offer an already accepted coach suggestion.
  const accepted = Array.isArray(graph.accepted_suggestion_ids)
    ? graph.accepted_suggestion_ids.filter((id): id is string => typeof id === 'string')
    : undefined;
  return { ...value,
    graph: { nodes: graph.nodes as CanvasGraph['nodes'], edges: graph.edges as CanvasGraph['edges'],
      ...(accepted !== undefined ? { accepted_suggestion_ids: accepted } : {}) } };
}

/** Read one owned notebook's canvas list without graph bodies. */
export async function readCanvases(thread: string, signal: AbortSignal): Promise<CanvasSummaries> {
  return confirmed(await readerCanvases({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Create one owned persistent canvas and return its owner-fenced projection. */
export async function createCanvas(thread: string, title: string, graph: CanvasGraph,
                                   signal: AbortSignal): Promise<Canvas> {
  return canvasView(confirmed(await readerCanvasCreate({ client: browserClient, signal,
    path: { thread_id: thread }, body: { title, graph: { ...graph } } })));
}

/** Read one owned canvas with its canonical graph. */
export async function readCanvas(thread: string, canvasId: string, signal: AbortSignal): Promise<Canvas> {
  return canvasView(confirmed(await readerCanvas({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: canvasId } })));
}

/** Delete the confirmed canvas revision and return the former server summary. */
export async function deleteCanvas(thread: string, id: string, revision: number, signal: AbortSignal) {
  return confirmed(await readerCanvasDelete({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: id }, body: { revision, confirmed: true } }));
}

/** Read the current durable review and server-owned eligibility for one chat. */
export async function readDeepReview(thread: string, signal: AbortSignal) {
  return confirmed(await readerDeepReview({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Explicitly enqueue a Deep Review for one chat. */
export async function startDeepReview(thread: string, signal: AbortSignal) {
  return confirmed(await readerDeepReviewStart({ client: browserClient, signal, path: { thread_id: thread } }));
}

/** Request cancellation only for the displayed review. */
export async function cancelDeepReview(thread: string, reviewId: string, signal: AbortSignal) {
  return confirmed(await readerDeepReviewCancel({ client: browserClient, signal, path: { thread_id: thread },
    body: { review_id: reviewId } }));
}

/** Apply one explicit revision-guarded save and return the confirmed canvas. */
export async function saveCanvas(thread: string, canvasId: string, graph: CanvasGraph,
                                 revision: number, title: string | null, signal: AbortSignal): Promise<Canvas> {
  return canvasView(confirmed(await readerCanvasUpdate({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: canvasId },
    body: { graph: { ...graph }, revision, ...(title !== null ? { title } : {}) } })));
}

/** Read one owned canvas's bounded version history without graph bodies. */
export async function readCanvasVersions(thread: string, canvasId: string,
                                         signal: AbortSignal): Promise<CanvasVersions> {
  return confirmed(await readerCanvasVersions({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: canvasId } }));
}

/** Read one owned version's readable preview. */
export async function readCanvasVersion(thread: string, canvasId: string, revision: number,
                                        signal: AbortSignal): Promise<CanvasVersion> {
  const value = confirmed(await readerCanvasVersion({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: canvasId, revision } }));
  const graph = value.graph as { nodes?: unknown; edges?: unknown };
  if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new ApiError(502);
  return { ...value,
    graph: { nodes: graph.nodes as CanvasGraph['nodes'], edges: graph.edges as CanvasGraph['edges'] } };
}

/** Restore an older version as a new revision guarded by the seen one. */
export async function restoreCanvasVersion(thread: string, canvasId: string, versionRevision: number,
                                           seenRevision: number, signal: AbortSignal): Promise<Canvas> {
  return canvasView(confirmed(await readerCanvasRestore({ client: browserClient, signal,
    path: { thread_id: thread, canvas_id: canvasId, revision: versionRevision },
    body: { revision: seenRevision } })));
}

/** Download one owned canvas export (JSON, outline or SVG) as an inert attachment. */
export async function downloadCanvasExport(
  thread: string, canvasId: string, format: 'json' | 'outline' | 'svg',
  title: string, signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/reader/threads/${encodeURIComponent(thread)}/canvases/${encodeURIComponent(canvasId)}/export?format=${format}`, {
    credentials: 'same-origin', cache: 'no-store', signal,
  });
  if (!response.ok) throw new ApiError(response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.${format === 'outline' ? 'txt' : format}`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Download one owned artifact export (Markdown, plaintext or JSON) as an inert attachment. */
export async function downloadArtifactExport(
  thread: string, artifactId: string, format: 'markdown' | 'text' | 'json',
  title: string, signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/reader/threads/${encodeURIComponent(thread)}/artifacts/${encodeURIComponent(artifactId)}/export?format=${format}`, {
    credentials: 'same-origin', cache: 'no-store', signal,
  });
  if (!response.ok) throw new ApiError(response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.${format === 'markdown' ? 'md' : format}`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Download the selected project export (conversation, summary, Thinking Path and
 * the chosen documents/canvases) as one inert structured attachment.
 */
export async function downloadProjectExport(
  thread: string, title: string, artifactIds: string[], canvasIds: string[],
  signal: AbortSignal,
): Promise<void> {
  const selection = new URLSearchParams();
  if (artifactIds.length) selection.set('artifacts', artifactIds.join(','));
  if (canvasIds.length) selection.set('canvases', canvasIds.join(','));
  const response = await fetch(`/api/v1/reader/threads/${encodeURIComponent(thread)}/project/export?${selection}`, {
    credentials: 'same-origin', cache: 'no-store', signal,
  });
  if (!response.ok) throw new ApiError(response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}-project.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

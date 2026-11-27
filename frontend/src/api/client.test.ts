/** Exercise the generated transport and compatibility adapter with synthetic responses. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  browserClient, createArtifact, createCanvas, createThread, discardUpload,
  linkLibrarySource, moveThread,
  readArtifacts, readArtifact, readBookmarks, readCanvas, readCanvases, readCanvasVersion,
  readCanvasVersions, readMessagePage,
  readNotebookList, readNotebookSettings,
  readPreferences, readProject, readSession, readSourceDetail, readSources, readThreadWorkspace,
  readUploads, removeSource, removeThread, requestProjectBrief, resolveTransition, retryUpload,
  restoreCanvasVersion, saveArtifact, saveCanvas, selectStage, setSourceSelected, setStar,
  updateNotebookSettings, updatePreferences,
} from './client';
import { ApiError } from './errors';

afterEach(() => { vi.unstubAllGlobals(); });

function reply(body: unknown, status = 200) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn().mockResolvedValue(Response.json(body, { status }));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

describe('generated reader transport', () => {
  it('retains same-origin cookies, no-store and caller cancellation', async () => {
    const session = { owner_id: 'owner-a', kind: 'guest', display_name: 'Student' };
    const fetch = reply(session);
    const controller = new AbortController();
    expect(await readSession(controller.signal)).toEqual(session);
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.url).toBe('https://app.test/api/v1/reader/session');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
    controller.abort();
    expect(request.signal.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 404, 409, 503])('preserves HTTP %s without displaying private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readSession(new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('preserves abort errors without retry', async () => {
    const error = new DOMException('Aborted', 'AbortError');
    const fetch = reply(null);
    fetch.mockRejectedValue(error);
    await expect(readSession(new AbortController().signal)).rejects.toBe(error);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('adapts omitted documented list defaults without changing ownership', async () => {
    reply({ owner_id: 'owner-a', notebooks: [{ id: 'chat', name: 'Saved' }], chat_summaries: {} });
    const list = await readNotebookList(new AbortController().signal);
    expect(list.owner_id).toBe('owner-a');
    expect(list.notebooks).toEqual([{ id: 'chat', name: 'Saved', kind: 'chat', pinned: false, parent_notebook_id: null }]);
  });

  it('encodes page parameters and normalizes optional visible message fields', async () => {
    const fetch = reply({ owner_id: 'owner-a', notebook: { id: 'thread/a', name: 'Saved' },
      messages: [{ id: 'm1', role: 'assistant', content: 'Answer', citations: [{ label: 'S1', source_id: 's1', title: 'Lecture' }] }],
      next_cursor: null, total_count: 1, conversation_revision: 3 });
    const page = await readMessagePage('thread/a', new AbortController().signal, 'revision+cursor', 100);
    const url = new URL((fetch.mock.calls[0][0] as Request).url);
    expect(url.pathname).toContain('thread%2Fa');
    expect(url.searchParams.get('cursor')).toBe('revision+cursor');
    expect(url.searchParams.get('limit')).toBe('100');
    expect(page.conversation_revision).toBe(3);
    expect(page.messages[0]).toMatchObject({ starred: false, feedback_available: false, rating: null });
    expect(page.messages[0].citations[0].excerpt).toBe('');
  });
});

describe('generated preference and notebook-settings operations', () => {
  const preferences = { owner_id: 'owner-a', appearance: 'Dark', display_name: 'Kai',
    reduce_motion: false, default_mode: 'project', starter_prompts: true };
  const settings = { owner_id: 'owner-a', notebook: { id: 'thread/a', name: 'Saved', kind: 'chat', pinned: false, parent_notebook_id: null },
    response_detail: 'long', response_language: 'English', selected_model: 'mock',
    reasoning_effort: null, assignment: {}, models: [], chat_model_label: 'Mock coach' };

  it('reads workspace preferences with the existing cookie and cancellation policy', async () => {
    const fetch = reply(preferences);
    const controller = new AbortController();
    expect(await readPreferences(controller.signal)).toEqual(preferences);
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/preferences');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
    controller.abort();
    expect(request.signal.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('saves only supplied preference keys through the generated POST contract', async () => {
    const fetch = reply(preferences);
    const saved = await updatePreferences({ appearance: 'Dark' }, new AbortController().signal);
    expect(saved).toEqual(preferences);
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/preferences');
    expect(request.headers.get('content-type')).toContain('application/json');
    expect(await request.text()).toBe(JSON.stringify({ appearance: 'Dark' }));
  });

  it('reads and saves one owner-fenced notebook settings projection', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json(settings))
      .mockResolvedValueOnce(Response.json(settings));
    vi.stubGlobal('fetch', fetch);
    expect(await readNotebookSettings('thread/a', new AbortController().signal)).toEqual(settings);
    expect(new URL((fetch.mock.calls[0][0] as Request).url).pathname).toContain('thread%2Fa');
    await updateNotebookSettings('thread/a', { name: 'Renamed' }, new AbortController().signal);
    const write = fetch.mock.calls[1][0] as Request;
    expect(write.method).toBe('POST');
    expect(new URL(write.url).pathname).toContain('thread%2Fa');
    expect(new URL(write.url).pathname.endsWith('/settings')).toBe(true);
    expect(await write.text()).toBe(JSON.stringify({ name: 'Renamed' }));
  });

  it.each([401, 403, 404, 422])('preserves HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readPreferences(new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(updatePreferences({ appearance: 'Dark' }, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(readNotebookSettings('thread/a', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(updateNotebookSettings('thread/a', { name: 'x' }, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(4);
  });
});

describe('generated notebook lifecycle operations', () => {
  const settings = { owner_id: 'owner-a', notebook: { id: 'thread/a', name: 'Saved', kind: 'chat', pinned: false, parent_notebook_id: null },
    response_detail: 'long', response_language: 'English', selected_model: 'mock',
    reasoning_effort: null, assignment: {}, models: [], chat_model_label: 'Mock coach' };

  it('creates an owned notebook through the generated POST contract', async () => {
    const fetch = reply(settings);
    const created = await createThread({ name: 'Studio project' }, new AbortController().signal);
    expect(created).toEqual(settings);
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
    expect(await request.text()).toBe(JSON.stringify({ name: 'Studio project' }));
  });

  it('moves a chat and confirms a deletion through the generated POST contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json(settings))
      .mockResolvedValueOnce(Response.json({ owner_id: 'owner-a', status: 'deleted' }));
    vi.stubGlobal('fetch', fetch);
    const moved = await moveThread('thread/a', 'thread/b', new AbortController().signal);
    expect(moved).toEqual(settings);
    const move = fetch.mock.calls[0][0] as Request;
    expect(new URL(move.url).pathname).toBe('/api/v1/reader/threads/thread%2Fa/move');
    expect(await move.text()).toBe(JSON.stringify({ parent_notebook_id: 'thread/b' }));
    const removed = await removeThread('thread/a', new AbortController().signal);
    expect(removed).toEqual({ owner_id: 'owner-a', status: 'deleted' });
    const remove = fetch.mock.calls[1][0] as Request;
    expect(new URL(remove.url).pathname).toBe('/api/v1/reader/threads/thread%2Fa/remove');
    expect(await remove.text()).toBe(JSON.stringify({ confirmed: true }));
  });

  it.each([401, 403, 404, 422])('preserves lifecycle HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(createThread({ name: 'x' }, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(moveThread('t', null, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(removeThread('t', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('reads one bounded owner-consistent workspace projection set', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn().mockResolvedValue(Response.json({
      owner_id: 'owner-a',
      page: { owner_id: 'owner-a', notebook: { id: 'thread/a', name: 'Saved' }, messages: [], next_cursor: null, total_count: 0, conversation_revision: 2 },
      project: { owner_id: 'owner-a', thread_id: 'thread/a', current_stage: 'framing', stages: [], pending: null,
        review: { summary: '', strengths: [], improvements: [], facione_scores: [],
          project_brief: { status: 'missing', version: '', brief: null } } },
      bookmarks: { owner_id: 'owner-a', thread_id: 'thread/a', conversation_revision: 2, messages: [] },
      settings: { owner_id: 'owner-a', notebook: { id: 'thread/a', name: 'Saved' }, response_detail: 'long',
        response_language: 'English', selected_model: 'mock', reasoning_effort: null, assignment: {}, models: [] },
    }));
    vi.stubGlobal('fetch', fetch);
    const value = await readThreadWorkspace('thread/a', new AbortController().signal);
    expect(value.page.notebook).toEqual({ id: 'thread/a', name: 'Saved', kind: 'chat', pinned: false, parent_notebook_id: null });
    expect(value.settings.notebook.kind).toBe('chat');
    expect(value.bookmarks.thread_id).toBe('thread/a');
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/thread%2Fa/workspace');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
  });
});

describe('generated source metadata operations', () => {
  const source = { id: 's1', title: 'Field notes', selected: false, locked: false, kind: 'file', size: 1024 };
  const catalog = { owner_id: 'owner-a', thread_id: 't1', sources: [source], max_files: 5, max_file_bytes: 1024 };
  const detail = { source, text: 'Extracted text', truncated: false };
  const uploads = { owner_id: 'owner-a', thread_id: 't1', jobs: [] };

  it('reads one owner-fenced catalog, preview and upload receipts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json(catalog))
      .mockResolvedValueOnce(Response.json(detail))
      .mockResolvedValueOnce(Response.json(uploads));
    vi.stubGlobal('fetch', fetch);
    expect(await readSources('t1', new AbortController().signal)).toEqual(catalog);
    expect(await readSourceDetail('t1', 's1', new AbortController().signal)).toEqual(detail);
    expect(await readUploads('t1', new AbortController().signal)).toEqual(uploads);
    expect(new URL((fetch.mock.calls[1][0] as Request).url).pathname)
      .toBe('/api/v1/reader/threads/t1/sources/s1');
  });

  it('writes selection, link and confirmed removal through generated POST contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json({ ...catalog, sources: [{ ...source, selected: true }] }))
      .mockResolvedValueOnce(Response.json(catalog))
      .mockResolvedValueOnce(Response.json(catalog));
    vi.stubGlobal('fetch', fetch);
    await setSourceSelected('t1', 's1', true, new AbortController().signal);
    await linkLibrarySource('t1', 's1', new AbortController().signal);
    await removeSource('t1', 's1', new AbortController().signal, true);
    const [select, link, remove] = fetch.mock.calls.map(([request]) => request as Request);
    expect(select.method).toBe('POST');
    expect(new URL(select.url).pathname).toBe('/api/v1/reader/threads/t1/sources/s1/select');
    expect(await select.text()).toBe(JSON.stringify({ selected: true }));
    expect(new URL(link.url).pathname).toBe('/api/v1/reader/threads/t1/sources/s1/link');
    expect(link.body).toBeNull();
    expect(new URL(remove.url).pathname).toBe('/api/v1/reader/threads/t1/sources/s1/remove');
    expect(await remove.text()).toBe(JSON.stringify({ confirmed: true }));
  });

  it('detaches a notebook source without a confirmation body', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn().mockResolvedValue(Response.json(catalog));
    vi.stubGlobal('fetch', fetch);
    await removeSource('t1', 's1', new AbortController().signal);
    const request = fetch.mock.calls[0][0] as Request;
    expect(await request.text()).toBe('');
  });

  it('retries and dismisses one owned upload receipt', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json({ accepted: true }, { status: 202 }))
      .mockResolvedValueOnce(Response.json({ discarded: true }));
    vi.stubGlobal('fetch', fetch);
    expect(await retryUpload('t1', 'u1', new AbortController().signal)).toEqual({ accepted: true });
    expect(await discardUpload('t1', 'u1', new AbortController().signal)).toEqual({ discarded: true });
    const [retry, discard] = fetch.mock.calls.map(([request]) => request as Request);
    expect(new URL(retry.url).pathname).toBe('/api/v1/reader/threads/t1/uploads/u1/retry');
    expect(new URL(discard.url).pathname).toBe('/api/v1/reader/threads/t1/uploads/u1/discard');
  });

  it.each([401, 403, 404, 409])('preserves source HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readSources('t1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(setSourceSelected('t1', 's1', true, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(removeSource('t1', 's1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(retryUpload('t1', 'u1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(discardUpload('t1', 'u1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(5);
  });
});

describe('generated bookmark and star operations', () => {
  const bookmarks = { owner_id: 'owner-a', thread_id: 't1', conversation_revision: 3, messages: [
    { id: 'm1', role: 'user' as const, preview: 'My reasoning', stage_id: 'framing', interaction_intent: null } ] };

  it('reads one owner/revision-fenced bookmark projection', async () => {
    const fetch = reply(bookmarks);
    const controller = new AbortController();
    expect(await readBookmarks('t1', controller.signal)).toEqual(bookmarks);
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/bookmarks');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
    controller.abort();
    expect(request.signal.aborted).toBe(true);
  });

  it('saves one explicit star through the generated POST contract', async () => {
    const fetch = reply({ starred: true });
    expect(await setStar('t1', 'm1', true, new AbortController().signal)).toEqual({ starred: true });
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/messages/m1/star');
    expect(await request.text()).toBe(JSON.stringify({ starred: true }));
  });

  it.each([401, 403, 404])('preserves bookmark HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readBookmarks('t1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(setStar('t1', 'm1', true, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});

describe('generated project progress operations', () => {
  const project = { owner_id: 'owner-a', thread_id: 't1', current_stage: 'framing', stages: [], pending: null,
    review: { summary: '', strengths: [], improvements: [], facione_scores: [],
      project_brief: { status: 'missing', version: '', brief: null } } };

  it('reads one owner-fenced project projection', async () => {
    const fetch = reply(project);
    const controller = new AbortController();
    // The documented recaps default is materialized as an empty list.
    expect(await readProject('t1', controller.signal)).toEqual({ ...project, recaps: [] });
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/project');
    expect(request.credentials).toBe('same-origin');
    expect(request.cache).toBe('no-store');
    controller.abort();
    expect(request.signal.aborted).toBe(true);
  });

  it('applies one explicit decision and one stage selection through generated POST contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn((_request: Request) => Promise.resolve(Response.json(project)));
    vi.stubGlobal('fetch', fetch);
    await resolveTransition('t1', 'pending-1', true, new AbortController().signal);
    await selectStage('t1', 'concept_generation', new AbortController().signal);
    const [resolve, select] = fetch.mock.calls.map(([request]) => request as Request);
    expect(new URL(resolve.url).pathname).toBe('/api/v1/reader/threads/t1/project/resolve/pending-1');
    expect(await resolve.text()).toBe(JSON.stringify({ accepted: true }));
    expect(new URL(select.url).pathname).toBe('/api/v1/reader/threads/t1/project/select-stage');
    expect(await select.text()).toBe(JSON.stringify({ stage_id: 'concept_generation' }));
  });

  it.each([401, 403, 404, 409])('preserves project HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readProject('t1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(resolveTransition('t1', 'p', true, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(selectStage('t1', 'framing', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

describe('generated project-brief operation', () => {  const brief = { status: 'current', version: 'v2', brief: { who_and_why: { text: 'Students', evidence: [] },
    problem: { text: null, evidence: [] }, current_idea: { text: null, evidence: [] },
    what_matters: { text: null, evidence: [] }, still_to_explore: { text: null, evidence: [] } } };

  it('requests one explicit whole-chat summary through the generated POST contract', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn((_request: Request) => Promise.resolve(Response.json(brief)));
    vi.stubGlobal('fetch', fetch);
    const value = await requestProjectBrief('t1', true, new AbortController().signal);
    expect(value.version).toBe('v2');
    expect(value.brief?.who_and_why).toEqual({ text: 'Students', evidence: [] });
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/project/brief');
    expect(await request.text()).toBe(JSON.stringify({ retry: true }));
  });

  it.each([401, 403, 404, 429, 503])('preserves brief HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(requestProjectBrief('t1', false, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('generated persistent artifact operations', () => {
  const document = { type: 'doc' as const, content: [{ type: 'paragraph' }] };
  const artifact = { owner_id: 'owner-a', thread_id: 't1', id: 'a1', title: 'Field notes',
    document, schema_version: 1, revision: 1, origin: 'editor',
    created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z', references: [] };

  it('creates, reads, lists and saves one owned artifact through generated contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn((_request: Request) => Promise.resolve(Response.json(
      new URL((_request as Request).url).pathname.endsWith('/artifacts') && (_request as Request).method === 'GET'
        ? { owner_id: 'owner-a', thread_id: 't1', artifacts: [{ ...artifact, document: undefined }] }
        : artifact)));
    vi.stubGlobal('fetch', fetch);
    const created = await createArtifact('t1', 'Field notes', document, new AbortController().signal, 'notes');
    expect(created).toEqual(artifact);
    expect(await readArtifact('t1', 'a1', new AbortController().signal)).toEqual(artifact);
    const listed = await readArtifacts('t1', new AbortController().signal);
    expect(listed.artifacts[0].id).toBe('a1');
    await saveArtifact('t1', 'a1', document, 1, 'Renamed', new AbortController().signal);
    const [create, read, list, save] = fetch.mock.calls.map(([request]) => request as Request);
    expect(new URL(create.url).pathname).toBe('/api/v1/reader/threads/t1/artifacts');
    expect(await create.text()).toBe(JSON.stringify({ title: 'Field notes', kind: 'notes', document }));
    expect(new URL(read.url).pathname).toBe('/api/v1/reader/threads/t1/artifacts/a1');
    expect(new URL(list.url).pathname).toBe('/api/v1/reader/threads/t1/artifacts');
    expect(new URL(save.url).pathname).toBe('/api/v1/reader/threads/t1/artifacts/a1');
    expect(await save.text()).toBe(JSON.stringify({ document, revision: 1, title: 'Renamed' }));
  });

  it('sends the create request id and draft origin when supplied', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn((_request: Request) => Promise.resolve(Response.json(artifact)));
    vi.stubGlobal('fetch', fetch);
    await createArtifact('t1', 'Field notes', document, new AbortController().signal, 'notes',
      undefined, 'draft:cd-1', 'coach_draft');
    const request = fetch.mock.calls[0][0] as Request;
    expect(await request.text()).toBe(JSON.stringify({
      title: 'Field notes', kind: 'notes', document, request_id: 'draft:cd-1',
      origin: 'coach_draft' }));
  });

  it.each([401, 403, 404, 409, 422])('preserves artifact HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(createArtifact('t1', 'x', document, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(readArtifact('t1', 'a1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(saveArtifact('t1', 'a1', document, 1, null, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

describe('generated design canvas operations', () => {
  const graph = { nodes: [{ id: 'n1', kind: 'problem' as const, title: 'P', description: '', x: 0, y: 0 }], edges: [] };
  const canvas = { owner_id: 'owner-a', thread_id: 't1', id: 'c1', title: 'Concept map',
    graph, schema_version: 1, revision: 1, origin: 'editor',
    created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z' };

  it('creates, reads, lists and saves one owned canvas through generated contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const fetch = vi.fn((request: Request) => Promise.resolve(Response.json(
      new URL(request.url).pathname.endsWith('/canvases') && request.method === 'GET'
        ? { owner_id: 'owner-a', thread_id: 't1', node_kinds: ['note'], relations: ['supports'],
            canvases: [{ ...canvas, graph: undefined }] }
        : canvas)));
    vi.stubGlobal('fetch', fetch);
    const created = await createCanvas('t1', 'Concept map', graph, new AbortController().signal);
    expect(created).toEqual(canvas);
    expect(await readCanvas('t1', 'c1', new AbortController().signal)).toEqual(canvas);
    const listed = await readCanvases('t1', new AbortController().signal);
    expect(listed.canvases[0].id).toBe('c1');
    await saveCanvas('t1', 'c1', graph, 1, 'Renamed', new AbortController().signal);
    const [create, read, list, save] = fetch.mock.calls.map(([request]) => request as Request);
    expect(new URL(create.url).pathname).toBe('/api/v1/reader/threads/t1/canvases');
    expect(await create.text()).toBe(JSON.stringify({ title: 'Concept map', graph }));
    expect(new URL(read.url).pathname).toBe('/api/v1/reader/threads/t1/canvases/c1');
    expect(new URL(list.url).pathname).toBe('/api/v1/reader/threads/t1/canvases');
    expect(new URL(save.url).pathname).toBe('/api/v1/reader/threads/t1/canvases/c1');
    expect(await save.text()).toBe(JSON.stringify({ graph, revision: 1, title: 'Renamed' }));
  });

  it('preserves accepted suggestion ids through the canvas projection', async () => {
    const withAccepted = { ...canvas, graph: { ...graph, accepted_suggestion_ids: ['sg-a', 'sg-b'] } };
    reply(withAccepted);
    const read = await readCanvas('t1', 'c1', new AbortController().signal);
    expect(read.graph.accepted_suggestion_ids).toEqual(['sg-a', 'sg-b']);
  });

  it.each([401, 403, 404, 409, 422])('preserves canvas HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(createCanvas('t1', 'x', graph, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(readCanvas('t1', 'c1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(saveCanvas('t1', 'c1', graph, 1, null, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('reads, previews and restores one owned canvas version through generated contracts', async () => {
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    const version = { owner_id: 'owner-a', thread_id: 't1', canvas_id: 'c1', revision: 1,
      title: 'Map', graph, origin: 'editor', restored_from: null, created_at: '2026-11-24T00:00:00Z' };
    const fetch = vi.fn((request: Request) => Promise.resolve(Response.json(
      new URL(request.url).pathname.endsWith('/versions') && request.method === 'GET'
        ? { owner_id: 'owner-a', thread_id: 't1', canvas_id: 'c1',
            versions: [{ revision: 1, title: 'Map', origin: 'editor', restored_from: null,
              created_at: '2026-11-24T00:00:00Z' }] }
        : version)));
    vi.stubGlobal('fetch', fetch);
    const list = await readCanvasVersions('t1', 'c1', new AbortController().signal);
    expect(list.versions[0].revision).toBe(1);
    expect(await readCanvasVersion('t1', 'c1', 1, new AbortController().signal)).toEqual(version);
    await restoreCanvasVersion('t1', 'c1', 1, 3, new AbortController().signal);
    const [listCall, read, restore] = fetch.mock.calls.map(([request]) => request as Request);
    expect(new URL(listCall.url).pathname).toBe('/api/v1/reader/threads/t1/canvases/c1/versions');
    expect(new URL(read.url).pathname).toBe('/api/v1/reader/threads/t1/canvases/c1/versions/1');
    expect(new URL(restore.url).pathname).toBe('/api/v1/reader/threads/t1/canvases/c1/versions/1/restore');
    expect(await restore.text()).toBe(JSON.stringify({ revision: 3 }));
  });

  it.each([401, 403, 404, 409])('preserves canvas version HTTP %s without echoing private detail', async status => {
    const fetch = reply({ detail: 'PRIVATE SERVER DETAIL' }, status);
    await expect(readCanvasVersions('t1', 'c1', new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(readCanvasVersion('t1', 'c1', 1, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    await expect(restoreCanvasVersion('t1', 'c1', 1, 2, new AbortController().signal)).rejects.toEqual(new ApiError(status));
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

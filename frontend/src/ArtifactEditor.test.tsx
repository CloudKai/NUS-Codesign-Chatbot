/**
 * @vitest-environment jsdom
 */
/** The artifact evidence panel links authorized sources with resolved availability. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ArtifactEditor } from './ArtifactEditor';
import { browserClient } from './api/client';
import type { Artifact } from './api';
import { draftKey } from './useArtifactAutosave';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

const savedArtifact: Artifact = {
  owner_id: 'a', thread_id: 't1', id: 'a1', title: 'Field notes', kind: 'notes',
  document: { type: 'doc', content: [] }, schema_version: 1, revision: 1, origin: 'editor',
  created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z', references: [],
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

it('links a notebook source to the artifact through an explicit guarded save', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const capturePut = vi.fn();
  const linked: Artifact = { ...savedArtifact, revision: 2, references: [
    { kind: 'source', id: 'src-1', available: true, title: 'Lecture slides' }] };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const method = input instanceof Request ? input.method : (init?.method ?? 'GET');
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (method === 'PUT' && url.includes('/artifacts/a1')) {
      capturePut(url, JSON.parse(typeof init?.body === 'string' ? init.body : await (input as Request).text()));
      return jsonResponse(linked);
    }
    if (url.includes('/sources')) return jsonResponse({ owner_id: 'a', thread_id: 't1',
      sources: [{ id: 'src-1', title: 'Lecture slides', selected: true, locked: false,
        kind: 'pdf', size: 10 }], max_files: 10, max_file_bytes: 1000 });
    return jsonResponse(savedArtifact);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByLabelText('Document title');
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  const picker = await screen.findByLabelText('Source to link');
  fireEvent.change(picker, { target: { value: 'src-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Link source' }));
  await waitFor(() => expect(screen.getByText('Evidence updated.')).toBeTruthy());
  expect(screen.getAllByText('Lecture slides').length).toBeGreaterThan(0);
  expect(capturePut).toHaveBeenCalledTimes(1);
  const body = capturePut.mock.calls[0][1] as { references: { kind: string; id: string }[] };
  expect(body.references).toEqual([{ kind: 'source', id: 'src-1' }]);
});

it('shows removed sources as unavailable instead of substituting content', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const removed: Artifact = { ...savedArtifact, revision: 2, references: [
    { kind: 'source', id: 'src-gone', available: false, title: null }] };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/sources')) return jsonResponse({ owner_id: 'a', thread_id: 't1',
      sources: [], max_files: 10, max_file_bytes: 1000 });
    return jsonResponse(removed);
  }));
  render(<ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByLabelText('Document title');
  fireEvent.click(screen.getByRole('button', { name: 'Evidence' }));
  expect(await screen.findByText('Unavailable or outdated evidence')).toBeTruthy();
});

it('keeps canvas and document provenance when linking and detaching a source', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const canonical = [
    { kind: 'canvas_node' as const, id: 'node-1', canvas_id: 'canvas-1' },
    { kind: 'artifact' as const, id: 'origin-1', revision: 3 },
  ];
  let saved: Artifact = { ...savedArtifact, references: canonical.map(reference => ({
    ...reference, available: true, title: reference.id,
  })) };
  const writes: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const method = input instanceof Request ? input.method : init?.method ?? 'GET';
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/sources')) return jsonResponse({
      owner_id: 'a', thread_id: 't1', sources: [{ id: 'src-1', title: 'Lecture slides' }],
      max_files: 10, max_file_bytes: 1000,
    });
    if (method === 'PUT') {
      const body = JSON.parse(typeof init?.body === 'string' ? init.body : await (input as Request).text());
      writes.push(body.references);
      saved = { ...saved, revision: saved.revision + 1, references: body.references.map(
        (reference: Artifact['references'][number]) => ({
          ...reference, available: true, title: reference.id === 'src-1' ? 'Lecture slides' : reference.id,
        }),
      ) };
    }
    return jsonResponse(saved);
  }));
  render(<ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={vi.fn()} onClose={vi.fn()}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Evidence' }));
  fireEvent.change(await screen.findByLabelText('Source to link'), { target: { value: 'src-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Link source' }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual([...canonical, { kind: 'source', id: 'src-1' }]);
  fireEvent.click(screen.getAllByRole('button', { name: 'Detach' })[2]);
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toEqual(canonical);
});

it('keeps a legacy document draft until the student chooses to reload the saved document', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  sessionStorage.setItem(draftKey('a', 'a1'), JSON.stringify({
    title: 'Unconfirmed notes',
    document: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Draft text' }] },
    ] },
  }));
  const writes = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const method = input instanceof Request ? input.method : (init?.method ?? 'GET');
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (method === 'PUT') writes();
    return jsonResponse({ ...savedArtifact, revision: 2, document: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Saved text' }] },
    ] } });
  }));
  render(<ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={vi.fn()} onClose={vi.fn()}/>);
  expect(await screen.findByText('Draft text')).toBeTruthy();
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Save' }).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Reload the saved document' }));
  expect(await screen.findByText('Saved text')).toBeTruthy();
  expect(screen.queryByText('Draft text')).toBeNull();
  expect(sessionStorage.getItem(draftKey('a', 'a1'))).toBeNull();
  expect(writes).not.toHaveBeenCalled();
});

it('offers Add to canvas from the saved document and opens the editable proposal', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const documented: Artifact = { ...savedArtifact, revision: 4, document: { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: 'Students cross unsafely at peak hours.' }] }] } };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.endsWith('/canvases')) return jsonResponse({ owner_id: 'a', thread_id: 't1',
      node_kinds: [], relations: [], stages: [], canvases: [] });
    return jsonResponse(documented);
  }));
  render(<ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={vi.fn()} onClose={vi.fn()}/>);
  await screen.findByLabelText('Document title');
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  // The dialog works from the saved revision, never from unsaved editor edits.
  expect(await screen.findByText(/saved version 4/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.queryByRole('dialog', { name: 'Add document content to a canvas' })).toBeNull();
});

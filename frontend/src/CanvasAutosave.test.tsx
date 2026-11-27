/**
 * @vitest-environment jsdom
 */
/** Canvas autosave: debounced outline edits collapse into one confirmed save; conflicts keep the draft. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { CanvasEditor } from './CanvasEditor';
import { browserClient } from './api/client';
import type { Canvas } from './api';
import { draftKey } from './useArtifactAutosave';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); sessionStorage.clear(); });

if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

const savedCanvas: Canvas = {
  owner_id: 'a', thread_id: 't1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 1, origin: 'editor', created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z',
  graph: { nodes: [], edges: [] },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: {
  put?: { status: number; body: Canvas }; getCanvas?: Canvas;
  capturePut?: (url: string, body: unknown) => void;
}) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    const bodyText = typeof init?.body === 'string' ? init.body
      : input instanceof Request ? await input.text() : undefined;
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (method === 'PUT' && url.includes('/canvases/c1')) {
      handlers.capturePut?.(url, bodyText ? JSON.parse(bodyText) as unknown : undefined);
      const put = handlers.put ?? { status: 200, body: savedCanvas };
      return jsonResponse(put.body, put.status);
    }
    if (url.includes('/canvases/c1')) {
      if (handlers.getCanvas) return jsonResponse(handlers.getCanvas);
      return jsonResponse(savedCanvas);
    }
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Fake timers break findBy and waitFor polling; flush microtasks until the outline renders. */
async function flushUntil(check: () => boolean): Promise<void> {
  for (let tick = 0; tick < 40 && !check(); tick += 1) {
    await vi.advanceTimersByTimeAsync(10);
  }
  expect(check()).toBe(true);
}

it('autosaves outline edits after the debounce without an explicit save press', async () => {
  vi.useFakeTimers();
  const capturePut = vi.fn();
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'note', title: 'First', description: '', x: 0, y: 0 },
  ], edges: [] } };
  const saved: Canvas = { ...open, revision: 2, graph: { nodes: [
    { id: 'n1', kind: 'note', title: 'First renamed!', description: '', x: 0, y: 0 },
  ], edges: [] } };
  stubBackend({ getCanvas: open, capturePut, put: { status: 200, body: saved } });
  render(<CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={vi.fn()} onClose={vi.fn()}/>);
  await flushUntil(() => Boolean(document.querySelector('#canvas-node-title')));
  // One outline burst: several edits inside one pause collapse into one save.
  fireEvent.change(screen.getByLabelText('Title', { selector: '#canvas-node-title' }),
    { target: { value: 'First renamed!' } });
  fireEvent.click(screen.getByText('Add node'));
  for (let tick = 0; tick < 40 && capturePut.mock.calls.length === 0; tick += 1) {
    await vi.advanceTimersByTimeAsync(100);
  }
  expect(capturePut).toHaveBeenCalledTimes(1);
  const body = capturePut.mock.calls[0][1] as { revision: number; graph: { nodes: { title: string }[] } };
  expect(body.revision).toBe(1);
  expect(body.graph.nodes).toHaveLength(2);
  expect(body.graph.nodes[1].title).toBe('First renamed!');
  await vi.advanceTimersByTimeAsync(100);
  expect(screen.getByText('All changes saved.')).toBeTruthy();
});

it('an autosave conflict keeps the unsaved graph visible with explicit resolutions', async () => {
  vi.useFakeTimers();
  const capturePut = vi.fn();
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'note', title: 'Mine', description: '', x: 0, y: 0 },
  ], edges: [] } };
  stubBackend({ getCanvas: open, capturePut, put: { status: 409, body: open } });
  render(<CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={vi.fn()} onClose={vi.fn()}/>);
  await flushUntil(() => Boolean(document.querySelector('#canvas-node-title')));
  fireEvent.change(screen.getByLabelText('Title', { selector: '#canvas-node-title' }),
    { target: { value: 'Mine v2' } });
  fireEvent.click(screen.getByText('Add node'));
  for (let tick = 0; tick < 40 && capturePut.mock.calls.length === 0; tick += 1) {
    await vi.advanceTimersByTimeAsync(100);
  }
  await vi.advanceTimersByTimeAsync(50);
  expect(capturePut).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/changed in another tab/)).toBeTruthy();
  // The losing graph is still visible in the outline.
  expect(screen.getAllByText(/Mine v2/).length).toBeGreaterThan(0);
});

it('reopens an older graph draft without authorizing a write over the current revision', async () => {
  vi.useFakeTimers();
  const capturePut = vi.fn();
  const current = { ...savedCanvas, revision: 2 };
  stubBackend({ getCanvas: current, capturePut, put: { status: 200, body: current } });
  sessionStorage.setItem(draftKey('a', 'c1', 'canvas'), JSON.stringify({
    title: 'Older draft', document: savedCanvas.graph, baseRevision: 1,
  }));
  render(<CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={vi.fn()} onClose={vi.fn()}/>);
  await flushUntil(() => Boolean(document.querySelector('#canvas-node-title')));
  expect(screen.getByDisplayValue('Older draft')).toBeTruthy();
  expect(screen.getByText(/changed in another tab/)).toBeTruthy();
  await vi.advanceTimersByTimeAsync(3000);
  expect(capturePut).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Keep my edits and save over' }));
  await flushUntil(() => capturePut.mock.calls.length > 0);
  expect(capturePut).toHaveBeenCalledWith(expect.any(String),
    expect.objectContaining({ revision: 2, title: 'Older draft' }));
});

it('recovers the original acknowledgement on refresh and writes only the later edit', async () => {
  vi.useFakeTimers();
  const capturePut = vi.fn();
  const committed = { ...savedCanvas, revision: 2, title: 'Committed title' };
  const later = { ...committed, revision: 3, title: 'Later edit' };
  stubBackend({ getCanvas: committed, capturePut, put: { status: 200, body: later } });
  sessionStorage.setItem(draftKey('a', 'c1', 'canvas'), JSON.stringify({
    title: 'Later edit', document: savedCanvas.graph, baseRevision: 1,
    attempt: { title: committed.title, document: committed.graph, baseRevision: 1 },
  }));
  render(<CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={vi.fn()} onClose={vi.fn()}/>);
  await flushUntil(() => capturePut.mock.calls.length > 0);
  expect(capturePut).toHaveBeenCalledTimes(1);
  expect(capturePut).toHaveBeenCalledWith(expect.any(String),
    expect.objectContaining({ revision: 2, title: 'Later edit' }));
  await vi.advanceTimersByTimeAsync(30);
  expect(sessionStorage.getItem(draftKey('a', 'c1', 'canvas'))).toBeNull();
});

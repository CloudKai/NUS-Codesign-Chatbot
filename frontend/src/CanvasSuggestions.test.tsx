/**
 * @vitest-environment jsdom
 */
/** Suggestion cards preview proposals and save only on explicit acceptance, guarding revisions. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CanvasSuggestions } from './CanvasSuggestions';
import { browserClient } from './api/client';
import type { Canvas, CanvasSuggestion } from './api';

// The read projection owned by api/client.ts is trimmed to nodes/edges today;
// this override supplies the saved acceptance ids the backend now persists so
// the card's already-applied branch is exercised end to end.
const clientOverrides = vi.hoisted(() => ({
  readCanvas: null as null | ((...args: [string, string, AbortSignal]) => Promise<Canvas>),
}));

vi.mock('./api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('./api/client')>();
  return {
    ...actual,
    readCanvas: (...args: Parameters<typeof actual.readCanvas>) =>
      (clientOverrides.readCanvas
        ? clientOverrides.readCanvas(...args)
        : actual.readCanvas(...args)),
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
  clientOverrides.readCanvas = null;
});

const savedCanvas: Canvas = {
  owner_id: 'a', thread_id: 'nb1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 3, origin: 'editor', created_at: '', updated_at: '',
  graph: { nodes: [{ id: 'n0', kind: 'problem', title: 'Unsafe crossing', description: '', x: 0, y: 0 }],
    edges: [{ id: 'e0', source: 'n0', target: 'n1', relation: 'addresses', explanation: '' }],
  },
};

const nodeSuggestion: CanvasSuggestion = {
  id: 'sg-mock-abc12345', kind: 'new_node', node_kind: 'concept',
  title: 'Idea: Unsafe crossing', description: 'Grade-separated crossing',
  rationale: 'The selected problem has no candidate concept yet.',
  base_canvas_id: 'c1', base_canvas_revision: 3,
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: { put?: { status: number }; capturePut?: (body: unknown) => void }) {
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
      handlers.capturePut?.(bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse({ ...savedCanvas, revision: 4 }, handlers.put?.status ?? 200);
    }
    if (url.includes('/canvases/c1')) return jsonResponse(savedCanvas);
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

it('returns focus to the review control when the review dialog closes', async () => {
  stubBackend({});
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  const dialog = screen.getByRole('dialog', { name: 'Review coach suggestion' }) as HTMLDialogElement;
  expect(dialog.open).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  const review = await screen.findByRole('button', { name: /Review suggestion/ });
  // Focus returns to the card's review control instead of falling to the page body.
  await waitFor(() => expect(document.activeElement).toBe(review));
});

it('accepts an edited node onto the suggested canvas with the fresh revision', async () => {  const capturePut = vi.fn();
  stubBackend({ capturePut });
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  const title = screen.getByLabelText('Node title') as HTMLInputElement;
  expect(title.value).toBe('Idea: Unsafe crossing');
  fireEvent.change(title, { target: { value: 'Protected crossing phase' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as { revision: number;
    graph: { nodes: { kind: string; title: string }[] } };
  expect(body.revision).toBe(3); // The card re-read the canvas and saved over the fresh revision.
  expect(body.graph.nodes.some(node => node.title === 'Protected crossing phase')).toBe(true);
  expect(screen.queryByText('Idea: Unsafe crossing')).toBeNull();
});

it('reports a stale canvas on 409 without losing the editable proposal', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut, put: { status: 409 } });
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(capturePut).toHaveBeenCalledTimes(1);
  // Nothing applied twice: the student still sees the editable proposal.
  expect((screen.getByLabelText('Node title') as HTMLInputElement).value).toBe('Idea: Unsafe crossing');
});

it('rejects and ignores without any save request', async () => {
  const fetchMock = stubBackend({});
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Reject suggestion' }));
  await waitFor(() => expect(screen.queryByText(/Idea: Unsafe crossing/)).toBeNull());
  // A different unhandled proposal: ignore also persists nothing.
  render(<CanvasSuggestions threadId="nb1" owner="other"
    suggestions={[{ ...nodeSuggestion, id: 'sg-mock-xyz98765' }]}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Dismiss suggestion' }));
  await waitFor(() => expect(screen.queryByText(/Idea: Unsafe crossing/)).toBeNull());
  expect(fetchMock.mock.calls.every(call => !String(call[0]).includes('PUT'))).toBe(true);
});

it('never offers the same suggestion twice after it was handled', async () => {
  stubBackend({});
  sessionStorage.setItem('codesign-suggestions:session:nb1', JSON.stringify([nodeSuggestion.id]));
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  expect(screen.queryByText(/Idea: Unsafe crossing/)).toBeNull();
});

it('reports an already-applied suggestion instead of closing silently', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut });
  clientOverrides.readCanvas = async () => ({ ...savedCanvas, graph: {
    ...savedCanvas.graph, accepted_suggestion_ids: [nodeSuggestion.id] } });
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  expect(await screen.findByText('This suggestion was already applied.')).toBeTruthy();
  // The saved canvas already holds the proposal: acceptance is not replayed.
  expect(capturePut).not.toHaveBeenCalled();
});

it('does not apply an accepted suggestion again after browser session storage is cleared', async () => {
  let current = structuredClone(savedCanvas);
  let saves = 0;
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = input instanceof Request ? input.method : init?.method ?? 'GET';
    if (method === 'PUT') {
      const body = JSON.parse(input instanceof Request ? await input.text() : String(init?.body));
      current = { ...current, graph: body.graph, revision: current.revision + 1 };
      saves += 1;
    }
    return jsonResponse(current);
  }));
  const first = render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Review suggestion' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  first.unmount();
  sessionStorage.clear();
  render(<CanvasSuggestions threadId="nb1" suggestions={[nodeSuggestion]}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Review suggestion' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add to canvas' }));
  await waitFor(() => expect(screen.getByText('This suggestion was already applied.')).toBeTruthy());
  expect(saves).toBe(1);
  expect(current.graph.nodes.filter(node => node.title === nodeSuggestion.title)).toHaveLength(1);
});

/**
 * @vitest-environment jsdom
 */
/** The develop dialog lets students pick nodes, assemble manually, or request a reviewed draft. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CanvasDevelopDialog } from './CanvasDevelopDialog';
import { browserClient } from './api/client';
import type { Canvas } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const canvas: Canvas = {
  owner_id: 'a', thread_id: 'nb1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 6, origin: 'editor', created_at: '', updated_at: '',
  graph: { nodes: [
    { id: 'n0', kind: 'problem', title: 'Unsafe crossing', description: 'left turns at peak hours', x: 0, y: 0 },
    { id: 'n1', kind: 'stakeholder', title: 'Students', description: 'cross twice daily', x: 200, y: 100 },
  ], edges: [] },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(capturePost?: (body: unknown) => void) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    if (methodOf(input, init) === 'POST' && url.endsWith('/artifacts')) {
      const bodyText = typeof init?.body === 'string' ? init.body
        : input instanceof Request ? await input.text() : undefined;
      capturePost?.(bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse({ owner_id: 'a', thread_id: 'nb1', id: 'art-new',
        title: 'Assembled', kind: 'notes', schema_version: 1, revision: 1,
        origin: 'editor', created_at: '', updated_at: '', references: [],
        document: { type: 'doc', content: [] } });
    }
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

it('assembles a new artifact from the checked nodes with node provenance', async () => {
  const capturePost = vi.fn();
  stubBackend(capturePost);
  const onDone = vi.fn();
  render(<CanvasDevelopDialog threadId="nb1" canvas={canvas} initialNodeIds={['n0']}
    onClose={() => {}} onDone={onDone}/>);
  fireEvent.click(await screen.findByRole('checkbox', { name: /Students/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Assemble myself' }));
  await waitFor(() => expect(capturePost).toHaveBeenCalledTimes(1));
  const body = capturePost.mock.calls[0][0] as { title: string;
    references: { kind: string; id: string; canvas_id?: string }[];
    document: { content: { content?: { text?: string }[] }[] } };
  const nodeRefs = body.references.filter(reference => reference.kind === 'canvas_node');
  expect(nodeRefs.map(reference => reference.id).sort()).toEqual(['n0', 'n1']);
  expect(nodeRefs.every(reference => reference.canvas_id === 'c1')).toBe(true);
  expect(JSON.stringify(body.document)).toContain('left turns at peak hours');
  expect(onDone).toHaveBeenCalledWith('art-new');
});

it('reuses one dialog request id across ambiguous assemble retries', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const posted: {
    request_id?: string; origin?: string;
    references: { kind: string; id: string; canvas_id?: string; revision?: number }[];
  }[] = [];
  let createAttempts = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : null;
    const url = request ? request.url : String(input);
    const method = request ? request.method : (init?.method ?? 'GET');
    if (method === 'POST' && url.endsWith('/artifacts')) {
      const bodyText = request ? await request.text() : String(init?.body ?? '');
      posted.push(JSON.parse(bodyText));
      createAttempts += 1;
      if (createAttempts === 1) throw new TypeError('network down');
      return jsonResponse({ owner_id: 'a', thread_id: 'nb1', id: 'art-new',
        title: 'Assembled', kind: 'notes', schema_version: 1, revision: 1,
        origin: 'editor', created_at: '', updated_at: '', references: [],
        document: { type: 'doc', content: [] } });
    }
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<CanvasDevelopDialog threadId="nb1" canvas={canvas} initialNodeIds={['n0']}
    onClose={() => {}} onDone={() => {}}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Assemble myself' }));
  await waitFor(() => expect(posted).toHaveLength(1));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toMatch(/couldn't confirm whether the artifact was created/i);
  expect(alert.textContent).not.toMatch(/Nothing was saved/i);
  // The payload is frozen after an ambiguous attempt so the retry is the same request.
  expect((screen.getAllByRole('checkbox')[0] as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('Artifact type') as HTMLSelectElement).disabled).toBe(true);

  fireEvent.click(screen.getByRole('button', { name: 'Assemble myself' }));
  await waitFor(() => expect(posted).toHaveLength(2));
  expect(posted[0].request_id).toBeTruthy();
  expect(posted[1].request_id).toBe(posted[0].request_id);
  expect(posted[1].origin).toBeUndefined();
  const nodeRefs = posted[1].references.filter(reference => reference.kind === 'canvas_node');
  expect(nodeRefs.every(reference => reference.revision === 6)).toBe(true);
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});

it('refuses to assemble with no nodes selected and asks the coach with the draft purpose', async () => {
  const capturePost = vi.fn();
  const fetchMock = stubBackend(capturePost);
  const onDiscuss = vi.fn();
  render(<CanvasDevelopDialog threadId="nb1" canvas={canvas} initialNodeIds={[]}
    onClose={() => {}} onDone={() => {}} onDiscuss={onDiscuss}/>);
  const assemble = await screen.findByRole('button', { name: 'Assemble myself' });
  expect(assemble).toHaveProperty('disabled', true);
  // Choosing nodes unlocks both actions; the coach request carries the draft purpose.
  fireEvent.click(screen.getByRole('checkbox', { name: /Unsafe crossing/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Students/ }));
  expect(assemble).toHaveProperty('disabled', false);
  fireEvent.click(screen.getByRole('button', { name: 'Draft with the coach' }));
  await waitFor(() => expect(onDiscuss).toHaveBeenCalledWith(
    'c1', 6, ['n0', 'n1'], 'draft synthesis', 'draft'));
  expect(fetchMock.mock.calls.every(call => !String(call[0]).endsWith('/artifacts'))).toBe(true);
});

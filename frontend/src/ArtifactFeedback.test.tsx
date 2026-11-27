/**
 * @vitest-environment jsdom
 */
/** Artifact feedback cards preview before/after and save only on explicit acceptance. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ArtifactFeedbackCard } from './ArtifactFeedback';
import { browserClient } from './api/client';
import type { Artifact, ArtifactFeedback } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

const savedArtifact: Artifact = {
  owner_id: 'a', thread_id: 'nb1', id: 'art1', title: 'Unsafe crossing notes',
  kind: 'notes', schema_version: 1, revision: 3, origin: 'editor',
  created_at: '', updated_at: '', references: [],
  document: { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: 'The crossing feels unsafe.' }] },
    { type: 'paragraph', content: [{ type: 'text', text: 'Older pedestrians rush the final seconds.' }] },
  ] },
};

const paragraphFeedback: ArtifactFeedback = {
  id: 'af-mock-abc12345', kind: 'revise_text',
  proposed_text: 'Older pedestrians rush the final seconds at the school crossing; '
    + 'success means nobody rushes.',
  rationale: 'Names the affected people and the intended outcome.',
  base_artifact_id: 'art1', base_artifact_revision: 3, paragraph: 1,
  original_text: 'Older pedestrians rush the final seconds.',
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: { put?: { status: number }; capturePut?: (body: unknown) => void;
  artifact?: Artifact }) {
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
    if (method === 'PUT' && url.includes('/artifacts/art1')) {
      handlers.capturePut?.(bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse({ ...savedArtifact, revision: 4 }, handlers.put?.status ?? 200);
    }
    if (url.includes('/artifacts/art1')) return jsonResponse(handlers.artifact ?? savedArtifact);
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

it('shows before and after and saves the edited passage with the fresh revision', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut });
  render(<ArtifactFeedbackCard threadId="nb1" feedback={paragraphFeedback}/>);
  expect(await screen.findByText('Older pedestrians rush the final seconds.')).toBeTruthy();
  expect(screen.getByText(/rush the final seconds at the school crossing/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Review suggestion/ }));
  const text = screen.getByLabelText('Revised text') as HTMLTextAreaElement;
  expect(text.value).toContain('school crossing');
  fireEvent.change(text, { target: { value: 'Older pedestrians wait safely, every time.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply to document' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as { revision: number;
    document: { content: { content?: { text?: string }[] }[] } };
  expect(body.revision).toBe(3); // The card re-read the artifact and saved over the fresh revision.
  expect(body.document.content[1].content?.[0]?.text).toBe('Older pedestrians wait safely, every time.');
  // The first paragraph is untouched.
  expect(body.document.content[0].content?.[0]?.text).toBe('The crossing feels unsafe.');
});

it('reports a stale document on 409 without losing the editable proposal', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut, put: { status: 409 } });
  render(<ArtifactFeedbackCard threadId="nb1" feedback={paragraphFeedback}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply to document' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(capturePut).toHaveBeenCalledTimes(1);
  expect((screen.getByLabelText('Revised text') as HTMLTextAreaElement).value)
    .toContain('school crossing');
});

it('rejects without any save request and never offers the same proposal twice', async () => {
  const fetchMock = stubBackend({});
  render(<ArtifactFeedbackCard threadId="nb1" owner="a" feedback={paragraphFeedback}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Reject suggestion' }));
  await waitFor(() => expect(screen.queryAllByText(/rush the final seconds/)).toHaveLength(0));
  expect(fetchMock.mock.calls.every(call => !String(call[0]).includes('PUT'))).toBe(true);
  // A replayed turn carrying the same proposal id is filtered by the handled record.
  render(<ArtifactFeedbackCard threadId="nb1" owner="a" feedback={paragraphFeedback}/>);
  expect(screen.queryAllByText(/rush the final seconds/)).toHaveLength(0);
});

it('applies whole-document feedback as explicit reviewed paragraphs', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut });
  render(<ArtifactFeedbackCard threadId="nb1" feedback={{
    ...paragraphFeedback, id: 'af-mock-xyz98765', paragraph: null,
    proposed_text: 'First refined paragraph.\n\nSecond refined paragraph.',
  }}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply to document' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as {
    document: { content: { type: string; content?: { text?: string }[] }[] } };
  expect(body.document.content).toHaveLength(2);
  expect(body.document.content[1].content?.[0]?.text).toBe('Second refined paragraph.');
});

it('preserves a newer document when the student accepts feedback from an earlier revision', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut, artifact: { ...savedArtifact, revision: 4, document: {
    type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Newly written evidence comes first.' }] },
      ...savedArtifact.document.content!,
    ],
  } } });
  render(<ArtifactFeedbackCard threadId="nb1" feedback={paragraphFeedback}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review suggestion/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply to document' }));
  expect((await screen.findByRole('alert')).textContent).toContain(
    'This document has changed since the feedback was generated.',
  );
  expect(capturePut).not.toHaveBeenCalled();
  expect((screen.getByLabelText('Revised text') as HTMLTextAreaElement).value)
    .toContain('school crossing');
});

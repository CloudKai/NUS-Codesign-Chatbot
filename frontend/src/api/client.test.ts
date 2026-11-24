/** Exercise the generated transport and compatibility adapter with synthetic responses. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { browserClient, readMessagePage, readNotebookList, readSession } from './client';
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

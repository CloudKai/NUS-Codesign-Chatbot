/** Reviewed generated reads with the existing cookie, cancellation and privacy policy. */
import { createClient } from './generated/client';
import { readerBootstrap, readerMessages, readerNotebooks, readerSession } from './generated/sdk.gen';
import type { ReaderNotebook } from './generated/types.gen';
import type { ReaderBootstrap } from './generated/types.gen';
import type { Notebook, NotebookList, Page, Session } from '../api';
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

/** Fetch one revision-bound page; pagination and request ownership remain server-owned. */
export async function readMessagePage(thread: string, signal: AbortSignal, cursor?: string | null, limit = 20): Promise<Page> {
  const page = confirmed(await readerMessages({ client: browserClient, signal,
    path: { thread_id: thread }, query: { limit, ...(cursor ? { cursor } : {}) } }));
  return { ...page, notebook: notebook(page.notebook), messages: page.messages.map(message => ({
    ...message, starred: message.starred ?? false, feedback_available: message.feedback_available ?? false,
    rating: message.rating ?? null,
    citations: (message.citations ?? []).map(citation => ({ ...citation, excerpt: citation.excerpt ?? '' })),
  })) };
}

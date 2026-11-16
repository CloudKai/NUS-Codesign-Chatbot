import type { Citation } from './stream';

/** Public reader contracts. Credentials stay in HttpOnly same-origin cookies. */
export interface Session { owner_id: string; display_name: string; kind: 'guest' | 'registered' }
export interface Notebook { id: string; name: string }
export interface Message { id: string; role: string; content: string; citations: Citation[] }
export interface NotebookList { owner_id: string; notebooks: Notebook[] }
export interface Page {
  owner_id: string; notebook: Notebook; messages: Message[];
  next_cursor: string | null; total_count: number; conversation_revision: number;
}

/** HTTP status supports fixed recovery copy without echoing private server errors. */
export class ApiError extends Error {
  constructor(public status: number) { super('Reader request failed'); }
}

/** Fetch JSON without retaining private browser HTTP cache entries. */
export async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', signal });
  if (!response.ok) throw new ApiError(response.status);
  return await response.json() as T;
}

/** Probe the owner, refreshing registered cookies through the existing auth route if needed. */
export async function currentSession(signal: AbortSignal): Promise<Session> {
  try { return await get<Session>('/api/v1/reader/session', signal); }
  catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    await get('/api/v1/auth/me', signal);
    return get<Session>('/api/v1/reader/session', signal);
  }
}

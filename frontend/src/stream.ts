/** Shared NDJSON coach lifecycle: previews are ephemeral; only done means saved. */
export interface Citation { source_id: string; label: string; title: string; excerpt: string; page?: number | null }

/** Citation text: "S1 · Title", plus ", p. 4" only when the saved citation has a page. */
export function citationText(citation: Citation): string {
  const page = typeof citation.page === 'number' && Number.isInteger(citation.page) && citation.page >= 1 ? `, p. ${citation.page}` : '';
  return `${citation.label} · ${citation.title}${page}`;
}
/** Sent on the stream request so the server may add reply_delta and reply_discard events. */
export const REPLY_DELTAS_HEADER = { 'X-Coach-Reply-Deltas': '1' };
export interface Turn { response_text: string; assessment: { citations: Citation[]; response_mode: string } }
export type Event =
  | { event: 'started'; thread_id: string; idempotency_key: string; stage: string }
  | { event: 'status'; phase: 'queued' | 'retrieving' | 'thinking' | 'saving'; label: string }
  | { event: 'reply_delta'; text: string }
  | { event: 'reply_discard' }
  | { event: 'reply_ready'; text: string }
  | { event: 'graph'; steps: string[]; mode: string | null }
  | { event: 'done'; turn: Turn }
  | { event: 'error'; status: number; detail: string; category?: string; retry_after?: number };

/** Reject malformed saved output before it can be presented as durable. */
export function isTurn(value: unknown): value is Turn {
  if (!value || typeof value !== 'object') return false;
  const turn = value as Turn;
  return typeof turn.response_text === 'string' && turn.response_text.length > 0
    && !!turn.assessment && typeof turn.assessment.response_mode === 'string'
    && Array.isArray(turn.assessment.citations) && turn.assessment.citations.every(citation =>
      citation && ['source_id', 'label', 'title', 'excerpt'].every(key => typeof citation[key as keyof Citation] === 'string')
      && (citation.page === undefined || citation.page === null || (Number.isInteger(citation.page) && citation.page >= 1)));
}

/** Validate discriminated events rather than trusting a TypeScript cast of network JSON. */
function decode(line: string): Event {
  const value = JSON.parse(line);
  const text = (key: string) => typeof value?.[key] === 'string';
  const valid = value && (
    (value.event === 'started' && text('thread_id') && text('idempotency_key') && text('stage')) ||
    (value.event === 'status' && ['queued', 'retrieving', 'thinking', 'saving'].includes(value.phase) && text('label')) ||
    (value.event === 'reply_delta' && text('text') && value.text.length > 0) ||
    (value.event === 'reply_discard') ||
    (value.event === 'reply_ready' && text('text') && value.text.length > 0) ||
    (value.event === 'graph' && Array.isArray(value.steps) && value.steps.every((step: unknown) => typeof step === 'string') && (value.mode === null || text('mode'))) ||
    (value.event === 'done' && isTurn(value.turn)) ||
    (value.event === 'error' && Number.isInteger(value.status) && value.status >= 400 && value.status <= 599 && text('detail'))
  );
  if (!valid) throw new Error('Malformed coach event');
  return value as Event;
}

/** Frame split UTF-8 chunks, CRLF, multiple lines and final unterminated records. Never replay. */
export async function readStream(response: Response, thread: string, key: string,
  onEvent: (event: Event) => void): Promise<void> {
  if (!response.body || !response.headers.get('content-type')?.includes('application/x-ndjson')) throw new Error('Missing coach stream');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  let started = false;
  let terminal = false;
  function accept(line: string) {
    if (!line.trim()) return;
    if (terminal) throw new Error('Event after completion');
    const event = decode(line);
    if (event.event === 'started') {
      if (started || event.thread_id !== thread || event.idempotency_key !== key) throw new Error('Wrong coach request');
      started = true;
    } else if (!started) throw new Error('Missing dispatch identity');
    terminal = event.event === 'done' || event.event === 'error';
    onEvent(event);
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (buffer.length > 2_000_000) throw new Error('Oversized coach record');
      let end: number;
      while ((end = buffer.indexOf('\n')) >= 0) {
        accept(buffer.slice(0, end).replace(/\r$/, ''));
        buffer = buffer.slice(end + 1);
      }
      if (done) { if (buffer.trim()) accept(buffer); break; }
    }
    if (!terminal) throw new Error('Coach stream ended before completion');
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

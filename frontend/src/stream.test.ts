/** Network framing and lifecycle regressions for the existing NDJSON parser. */
import { expect, it, vi } from 'vitest';
import { readStream } from './stream';

const started = { event: 'started', thread_id: 'chat', idempotency_key: 'key', stage: 'problem_identification' };
const done = { event: 'done', turn: { response_text: '你好', assessment: { response_mode: 'coaching', citations: [] } } };
function response(events: unknown[], split = false) {
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\r\n'));
  return new Response(new ReadableStream({ start(controller) {
    if (split) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    else controller.enqueue(bytes);
    controller.close();
  } }), { headers: { 'Content-Type': 'application/x-ndjson' } });
}

it('decodes byte-split UTF-8, CRLF and an unterminated final record', async () => {
  const received = vi.fn();
  await readStream(response([started, { event: 'reply_delta', text: '你好' }, done], true), 'chat', 'key', received);
  expect(received.mock.calls.map(([event]) => event.event)).toEqual(['started', 'reply_delta', 'done']);
  expect(received.mock.calls[1][0].text).toBe('你好');
});

it.each([
  [[done], 'Missing dispatch identity'],
  [[{ ...started, thread_id: 'foreign' }, done], 'Wrong coach request'],
  [[started, started, done], 'Wrong coach request'],
  [[started, done, done], 'Event after completion'],
  [[started, { event: 'reply_delta', text: '' }], 'Malformed coach event'],
  [[started, { event: 'status', phase: 'unknown', label: 'Pretend' }], 'Malformed coach event'],
  [[started, { event: 'error', status: 429, detail: 'Busy', category: 5 }], 'Malformed coach event'],
  [[started, { event: 'error', status: 429, detail: 'Busy', retry_after: -1 }], 'Malformed coach event'],
  [[started, { event: 'error', status: 429, detail: 'Busy', retry_after: '5' }], 'Malformed coach event'],
  [[started, { event: 'reply_delta', text: 'Unsaved' }], 'before completion'],
] as const)('rejects invalid lifecycle %# without replay', async (events, message) => {
  await expect(readStream(response([...events]), 'chat', 'key', vi.fn())).rejects.toThrow(message);
});

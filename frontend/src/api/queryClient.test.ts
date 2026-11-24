/** Verify private request cleanup using the actual TanStack Query cache. */
import { expect, it } from 'vitest';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';

it('separates owner keys and disables automatic replay and private retention', () => {
  const client = createReaderQueryClient();
  expect(queryKeys.notebooks('a')).not.toEqual(queryKeys.notebooks('b'));
  expect(client.getDefaultOptions()).toEqual({ queries: {
    staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false,
  }, mutations: { retry: false } });
  client.clear();
});

it('clears an old identity and prevents its delayed response from repopulating the cache', async () => {
  const client = createReaderQueryClient();
  let resolve!: (value: string) => void;
  let signal!: AbortSignal;
  const pending = client.fetchQuery({ queryKey: queryKeys.notebooks('a'), queryFn: context => {
    signal = context.signal;
    return new Promise<string>(done => { resolve = done; });
  } }).catch(() => undefined);
  client.clear();
  expect(signal.aborted).toBe(true);
  client.setQueryData(queryKeys.notebooks('b'), 'new identity');
  resolve('old private work');
  await pending;
  expect(client.getQueryData(queryKeys.notebooks('a'))).toBeUndefined();
  expect(client.getQueryData(queryKeys.notebooks('b'))).toBe('new identity');
  client.clear();
});

it('cancels a pre-mutation list read before accepting the confirmed replacement', async () => {
  const client = createReaderQueryClient();
  const key = queryKeys.notebooks('a');
  let resolve!: (value: string) => void;
  const pending = client.fetchQuery({ queryKey: key,
    queryFn: () => new Promise<string>(done => { resolve = done; }) }).catch(() => undefined);
  await client.cancelQueries({ queryKey: key });
  client.setQueryData(key, 'confirmed list');
  resolve('outdated list');
  await pending;
  expect(client.getQueryData(key)).toBe('confirmed list');
  client.clear();
});

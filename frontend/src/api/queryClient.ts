/** Privacy-first defaults; resource retention changes require lifecycle tests. */
import { QueryClient } from '@tanstack/react-query';

/** Create an ephemeral client: no persistence, automatic retry or background refetch. */
export function createReaderQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: {
    queries: { staleTime: 0, gcTime: 0, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false },
    mutations: { retry: false },
  } });
}

/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DeepReview } from './DeepReview';
import { currentSession } from './api';
import { cancelDeepReview, readDeepReview, startDeepReview } from './api/client';
import type { ReaderDeepReview, ReaderReviewJob } from './api/generated/types.gen';

vi.mock('./api', () => ({ currentSession: vi.fn() }));
vi.mock('./api/client', () => ({
  readDeepReview: vi.fn(),
  startDeepReview: vi.fn(),
  cancelDeepReview: vi.fn(),
}));

function state(status?: ReaderReviewJob['status']): ReaderDeepReview {
  return {
    owner_id: 'owner', thread_id: 'chat', eligible: true,
    job: status ? {
      review_id: 'displayed-review', status, reviewed_revision: 4, conversation_revision: 4,
      summary: null,
    } : null,
  };
}

function openReview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <DeepReview owner="owner" thread="chat" disabled={false}/>
  </QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(currentSession).mockResolvedValue({
    owner_id: 'owner', kind: 'guest', display_name: '',
  });
});
afterEach(cleanup);

it('starts explicitly, then cancels the displayed durable review', async () => {
  vi.mocked(readDeepReview).mockResolvedValue(state());
  vi.mocked(startDeepReview).mockResolvedValue(state('queued'));
  vi.mocked(cancelDeepReview).mockResolvedValue(state('cancel_requested'));
  openReview();
  fireEvent.click(await screen.findByRole('button', { name: 'Start Deep Review' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel Deep Review' }));
  expect(await screen.findByText(/Cancellation requested/)).toBeTruthy();
  expect(cancelDeepReview).toHaveBeenCalledWith('chat', 'displayed-review', expect.any(AbortSignal));
});

it('checks saved status after an uncertain start and waits for an explicit new request', async () => {
  vi.mocked(readDeepReview).mockResolvedValueOnce(state()).mockResolvedValue(state('ambiguous'));
  vi.mocked(startDeepReview).mockRejectedValueOnce(new Error('Connection closed'));
  openReview();
  fireEvent.click(await screen.findByRole('button', { name: 'Start Deep Review' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Check review status' }));
  expect(await screen.findByText(/previous review may have run/)).toBeTruthy();
  expect(await screen.findByRole('button', { name: 'Start a new Deep Review' })).toBeTruthy();
  expect(startDeepReview).toHaveBeenCalledTimes(1);
});

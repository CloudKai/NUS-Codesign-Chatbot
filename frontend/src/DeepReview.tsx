/** Controls for the current chat's persisted Deep Review job. */
import { useEffect, useId, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { currentSession } from './api';
import { cancelDeepReview, readDeepReview, startDeepReview } from './api/client';
import type { DeepReviewJobStatus, ReaderDeepReview } from './api/generated/types.gen';
import { queryKeys } from './api/queryKeys';
import { CoachText } from './CoachText';

const reviewStatus: Record<DeepReviewJobStatus, string> = {
  queued: 'Deep Review is queued.',
  running: 'Deep Review is in progress.',
  cancel_requested: 'Cancellation requested. A review already in progress may still finish.',
  cancelled: 'Deep Review was cancelled.',
  completed: 'Deep Review is saved.',
  failed: 'Deep Review could not finish. You can start a new review.',
  ambiguous: 'The previous review may have run, but no result was saved. Start a new review only if you want another attempt.',
};

function active(status?: DeepReviewJobStatus) {
  return status === 'queued' || status === 'running' || status === 'cancel_requested';
}

/** Poll only active work while the panel is visible; a failed write requires a fresh status check. */
export function DeepReview({ owner, thread, disabled }: { owner: string; thread: string; disabled: boolean }) {
  const heading = useId();
  const cache = useQueryClient();
  const key = queryKeys.deepReview(owner, thread);
  const running = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const query = useQuery({
    queryKey: key, retry: false,
    queryFn: async ({ signal }) => verified(await readDeepReview(thread, signal)),
    refetchInterval: state => active(state.state.data?.job?.status) ? 2_000 : false,
  });
  const job = query.data?.job;
  const status = job?.status;

  function verified(result: ReaderDeepReview) {
    if (result.owner_id !== owner || result.thread_id !== thread) throw new Error('Review owner changed');
    return result;
  }

  useEffect(() => () => { running.current?.abort(); }, []);

  async function submit(cancelId?: string) {
    if (running.current || unconfirmed || disabled) return;
    const request = new AbortController();
    running.current = request;
    setBusy(true);
    try {
      await cache.cancelQueries({ queryKey: key });
      if ((await currentSession(request.signal)).owner_id !== owner) throw new Error('Review owner changed');
      const result = verified(await (cancelId
        ? cancelDeepReview(thread, cancelId, request.signal) : startDeepReview(thread, request.signal)));
      if (request.signal.aborted) return;
      await cache.cancelQueries({ queryKey: key });
      if (!request.signal.aborted) cache.setQueryData(key, result);
    } catch {
      if (!request.signal.aborted) setUnconfirmed(true);
    } finally {
      running.current = null;
      if (!request.signal.aborted) setBusy(false);
    }
  }

  async function checkStatus() {
    const result = await query.refetch();
    if (result.isSuccess) setUnconfirmed(false);
  }

  return <section className="review-card" aria-labelledby={heading}>
    <h3 id={heading}>Deep Review</h3>
    {status ? <p role="status">{reviewStatus[status]}</p>
      : query.isPending ? <p role="status">Checking Deep Review…</p>
      : query.data?.eligible ? null
      : query.isError ? null
      : <p className="supporting">Finish the Thinking Path, including Reflection, to unlock Deep Review.</p>}
    {job && status === 'completed' && job.summary ? <CoachText text={job.summary}/> : null}
    {job && status === 'completed' && job.conversation_revision !== null
      && job.conversation_revision > job.reviewed_revision
      ? <p className="supporting">This review covers an earlier version of the conversation.</p> : null}
    {unconfirmed || query.isError ? <>
      <p role="alert">Could not confirm the current review. Check its saved status before another action.</p>
      <button type="button" disabled={busy || query.isFetching} onClick={() => void checkStatus()}>Check review status</button>
    </> : status === 'queued' || status === 'running'
      ? <button type="button" disabled={disabled || busy} onClick={() => void submit(job?.review_id)}>Cancel Deep Review</button>
      : query.data?.eligible && !active(status)
        ? <button type="button" disabled={disabled || busy} onClick={() => void submit()}>
          {job ? 'Start a new Deep Review' : 'Start Deep Review'}
        </button> : null}
  </section>;
}

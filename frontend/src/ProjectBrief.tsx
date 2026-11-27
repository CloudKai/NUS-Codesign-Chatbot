/** A compact, whole-conversation project brief; never infer facts in presentation code. */
import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ApiError, currentSession, type Project, type ProjectBriefResult } from './api';
import { requestProjectBrief } from './api/client';

const fields = [
  ['who_and_why', 'Who and why'], ['problem', 'Problem'], ['current_idea', 'Current idea'],
  ['what_matters', 'What matters'], ['still_to_explore', 'Still to explore'],
] as const;

/** Read the saved brief or request one summary for a changed chat; errors require explicit retry. */
export function ProjectBriefCard({ project, disabled, onSaved }: { project: Project; disabled: boolean; onSaved: (result: ProjectBriefResult) => void }) {
  const saved = project.review?.project_brief;
  const version = saved?.version ?? '';
  const [result, setResult] = useState<ProjectBriefResult | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const hintId = useId();
  const [dismissHint, setDismissHint] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const currentVersion = useRef(version);
  currentVersion.current = version;
  const view = saved?.status === 'current' ? saved : result?.version === version ? result : saved;
  useEffect(() => () => controller.current?.abort(), []);
  async function summarise(retry = false) {
    if (working || disabled) return;
    const request = new AbortController();
    controller.current?.abort(); controller.current = request;
    setWorking(true); setError('');
    try {
      // Generated explicit-generation write; reading cached state never starts
      // generation implicitly, and failures keep requiring the explicit retry.
      const next = await requestProjectBrief(project.thread_id, retry, request.signal);
      const owner = await currentSession(request.signal);
      if (request.signal.aborted || currentVersion.current !== version || owner.owner_id !== project.owner_id) return;
      // A concurrent new turn invalidates the request rather than displaying a partial or outdated brief.
      if (next.version !== version) throw new ApiError(409);
      setResult(next); onSaved(next);
    } catch (failure) {
      if (!request.signal.aborted && currentVersion.current === version) setError(failure instanceof ApiError && failure.status === 409
        ? 'The chat changed while summarising. Refresh the chat and try again.'
        : 'Could not summarise this chat. Try again.');
    } finally { if (!request.signal.aborted) setWorking(false); }
  }
  const current = view?.status === 'current' && view.brief;
  const note = working ? 'Summarising the whole chat…'
    : view?.status === 'preview' ? 'A whole-chat summary is unavailable in this preview.'
    : view?.status === 'empty' ? 'Your brief will take shape as you discuss your project.'
    : current ? '' : 'A summary of your users, problem and developing idea.';
  return <section className="review-card project-brief-card" aria-labelledby="project-brief-title" aria-busy={working}>
    <header className="brief-header">
      <h3 id="project-brief-title">Your project so far</h3>
      {working || error || view?.status === 'missing' || view?.status === 'failed' ? (
        <div className="brief-action" data-tooltip-dismissed={dismissHint || undefined}
          onPointerEnter={() => setDismissHint(false)}>
          <button className="primary brief-submit" type="button" disabled={working || disabled}
            aria-describedby={hintId} onFocus={() => setDismissHint(false)}
            onKeyDown={event => {
              if (event.key === 'Escape' && !dismissHint) {
                event.preventDefault();
                event.stopPropagation();
                setDismissHint(true);
              }
            }} onClick={() => void summarise(Boolean(error || view?.status === 'failed'))}>
            <Icon name="spark"/>{working ? 'Summarising…' : 'Summarise chat'}
          </button>
          <span id={hintId} className="brief-action-hint" role="tooltip">Summarises your whole chat.</span>
        </div>
      ) : null}
    </header>
    {note ? <p className="brief-note supporting" role="status">{note}</p> : null}
    {error || view?.status === 'failed' ? <p className="brief-error" role="alert">{error || 'The last summary could not be completed. You can try again.'}</p> : null}
    <dl className="project-brief-fields">{fields.map(([key, label]) => {
      const text = current ? current[key].text : null;
      return <div key={key} data-missing={!text || undefined}>
        <dt>{label}</dt><dd>{text || (view?.status === 'empty' || current ? 'Not yet established' : 'Not summarised yet')}</dd>
      </div>;
    })}</dl>

  </section>;
}

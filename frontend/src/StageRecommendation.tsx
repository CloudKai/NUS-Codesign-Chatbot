/** Inline stage decision card and milestone banner shown inside the transcript. */
import type { Project } from './api';
import { Icon } from './Icon';

export type Milestone = { kind: 'stage'; completed: number; total: number; next: string; from: string } | { kind: 'finished' };

export function StageRecommendation({ project, disabled, act }: {
  project: Project; disabled: boolean; act: (route: string, body: object) => Promise<void>;
}) {
  const pending = project.pending;
  if (!pending) return null;
  const target = project.stages.find(stage => stage.id === pending.to_stage)?.label ?? 'the next stage';
  const route = `resolve/${encodeURIComponent(pending.id)}`;
  return <section className="stage-card" aria-labelledby="stage-card-title">
    <h3 id="stage-card-title"><Icon name="path"/> Coach recommendation</h3>
    <p className="stage-card-target">Next stage: {target}</p>
    <p>{pending.rationale}</p>
    <div className="stage-actions">
      <button className="primary" disabled={disabled} onClick={() => void act(route, { accepted: true })}>Move to {target}</button>
      <button disabled={disabled} onClick={() => void act(route, { accepted: false })}>Stay here</button>
    </div>
  </section>;
}

export function MilestoneBanner({ milestone, onDismiss, onReview, onReflect }: {
  milestone: Milestone; onDismiss: () => void; onReview: () => void; onReflect: (stage: string) => void;
}) {
  return <section className="milestone" role="status" aria-label="Milestone">
    <span className="milestone-icon" aria-hidden="true"><Icon name="flag"/></span>
    <div className="milestone-text">
      {milestone.kind === 'stage'
        ? <><strong>Stage {milestone.completed} of {milestone.total} complete</strong><span>Next: {milestone.next}</span></>
        : <><strong>You finished the Thinking Path</strong><span>Open Review to see your summary, strengths and how your idea scores.</span></>}
    </div>
    {milestone.kind === 'finished' ? <button onClick={onReview}>Open Review</button>
      : <button onClick={() => onReflect(milestone.from)}>Add a reflection</button>}
    <button className="icon-button" aria-label="Dismiss milestone" title="Dismiss" onClick={onDismiss}><Icon name="close"/></button>
  </section>;
}

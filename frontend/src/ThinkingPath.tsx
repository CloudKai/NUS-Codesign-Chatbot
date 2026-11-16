/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useRef, useState } from 'react';
import type { Project } from './api';

/** Render explicit decisions, saved stage artifacts and application-authorized revisits. */
export function ThinkingPath({ project, disabled, act }: {
  project: Project; disabled: boolean; act: (route: string, body: object) => Promise<void>;
}) {
  const [opened, setOpened] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const current = project.stages.find(stage => stage.id === project.current_stage)!;
  const view = project.stages.find(stage => stage.id === opened) || current;
  const pending = project.pending;
  async function decide(route: string, body: object) {
    await act(route, body);
    heading.current?.focus({ preventScroll: true });
  }
  return <section className="thinking-path" aria-labelledby="path-heading">
    <h3 id="path-heading" ref={heading} tabIndex={-1}>Thinking Path · {current.label}</h3>
    <p className="next-action"><strong>Next action</strong><br/>{current.next_action}</p>
    {pending ? <div className="recommendation">
      <h4>Recommendation: {project.stages.find(stage => stage.id === pending.to_stage)?.label}</h4>
      <p>{pending.rationale}</p>
      <p className="supporting">Your active stage stays {current.label} until you confirm.</p>
      <div className="stage-actions">
        <button className="primary" disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: true })}>Confirm next stage</button>
        <button disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: false })}>Stay here</button>
      </div>
    </div> : null}
    <details className="saved-work">
      <summary>Saved project work and stage revisits</summary>
      <nav aria-label="Thinking Path stages" className="stage-list">
        {project.stages.map(stage => <button key={stage.id} aria-pressed={view.id === stage.id}
          onClick={() => setOpened(stage.id)}>{stage.label}<span>{stage.id === current.id ? 'Current' : stage.completed ? 'Completed' : stage.selectable ? 'Available' : 'Not yet available'}</span></button>)}
      </nav>
      <section className="stage-work" aria-label={`${view.label} saved work`}>
        <h4>{view.artifact_label}</h4>
        <p><strong>Your saved work</strong></p>
        {view.student_work.length ? view.student_work.map(work => <blockquote key={work.message_id}>{work.text}</blockquote>) : <p className="supporting">No stage-tagged project contribution saved here yet. Older unclassified work remains in chat.</p>}
        {view.coach_summary ? <><h4>Coach-generated summary</h4><p className="message-content">{view.coach_summary}</p></> : null}
        {view.feedback.length ? <details><summary>Saved coach feedback</summary>{view.feedback.map(work => <p className="message-content" key={work.message_id}>{work.text}</p>)}</details> : null}
        <p><strong>Next action</strong><br/>{view.next_action}</p>
        {view.id !== current.id ? <button disabled={disabled || !view.selectable} onClick={() => void decide('select-stage', { stage_id: view.id })}>
          {view.completed ? 'Revisit' : 'Continue in'} {view.label}</button> : <p className="supporting">You are working in this stage.</p>}
      </section>
    </details>
  </section>;
}

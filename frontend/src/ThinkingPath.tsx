/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useRef, useState, type ReactNode } from 'react';
import type { Project, ReviewFeedback, Stage } from './api';
import { CoachText } from './CoachText';
import { Icon } from './Icon';

const reviewTabs = ['Summary', 'Progression'] as const;

/** Show saved feedback and the explicit Thinking Path actions for this chat. */
export function ThinkingPath({ project, disabled, act, startInChat, onClose, status, children }: {
  project: Project; disabled: boolean; act: (route: string, body: object) => Promise<void>;
  startInChat: () => void; onClose: () => void; status: string; children: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<(typeof reviewTabs)[number]>(
    project.pending ? 'Progression' : 'Summary',
  );
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [opened, setOpened] = useState('');
  const current = project.stages.find(stage => stage.id === project.current_stage)!;
  const done = project.stages.filter(stage => stage.completed).length;
  const pending = project.pending;
  const review = project.review;
  const scores = review?.facione_scores ?? [];
  async function decide(route: string, body: object) {
    await act(route, body);
    document.getElementById('review-heading')?.focus({ preventScroll: true });
  }
  function selectTab(tab: (typeof reviewTabs)[number], button: HTMLButtonElement) {
    if (tab === activeTab) return;
    setActiveTab(tab);
    button.closest('dialog')?.scrollTo({ top: 0 });
    button.focus({ preventScroll: true });
  }

  return <section className="thinking-path">
    <div className="review-toolbar">
      <header className="review-header">
        <h2 id="review-heading" tabIndex={-1}>Review</h2>
        <button className="icon-button" aria-label="Close Review" title="Close Review" onClick={onClose}><Icon name="close"/></button>
      </header>
      <div className="review-tabs" role="tablist" aria-label="Review views">
        {reviewTabs.map((tab, index) => {
          const id = tab.toLowerCase();
          const selected = activeTab === tab;
          const pendingDecision = tab === 'Progression' && pending;
          return <button key={tab} ref={button => { tabButtons.current[index] = button; }}
            type="button" role="tab" id={`review-tab-${id}`} aria-controls={`review-panel-${id}`}
            aria-selected={selected} tabIndex={selected ? 0 : -1}
            aria-description={pendingDecision ? 'Stage decision pending' : undefined}
            onClick={event => selectTab(tab, event.currentTarget)}
            onKeyDown={event => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? reviewTabs.length - 1 : 1 - index;
              const button = tabButtons.current[next];
              if (button) selectTab(reviewTabs[next], button);
            }}>
            {tab}{pendingDecision ? <span className="decision-dot" aria-hidden="true"/> : null}
          </button>;
        })}
      </div>
    </div>
    <p className="review-status supporting" role="status">{status}</p>
    {children}
    <section id="review-panel-summary" role="tabpanel" aria-labelledby="review-tab-summary"
      hidden={activeTab !== 'Summary'} tabIndex={0}>
      <section className="review-section" aria-labelledby="review-summary">
        <h3 id="review-summary">Discussion summary</h3>
        <CoachText text={review?.summary || current.coach_summary || 'A summary will appear after the coach has reviewed your design reasoning.'}/>
      </section>
      <ReviewFeedbackSection title="Strengths" groups={review?.strengths ?? []} stages={project.stages} currentStage={current.id}/>
      <ReviewFeedbackSection title="Areas to improve" groups={review?.improvements ?? []} stages={project.stages} currentStage={current.id}/>
      <section className="review-section">
        <h3>Facione critical-thinking skills</h3>
        {scores.some(item => item.score !== null) ? <dl className="facione-scores">
          {scores.map(item => <div key={item.dimension}><dt>{item.dimension}</dt><dd>{item.score === null ? 'Not yet assessed' : `${item.score}/4`}</dd></div>)}
        </dl> : <p className="supporting">No Facione assessments yet.</p>}
      </section>
    </section>
    <section id="review-panel-progression" role="tabpanel" aria-labelledby="review-tab-progression"
      hidden={activeTab !== 'Progression'} tabIndex={0}>
      <section className="next-action" aria-label="Current stage and next step">
        <h3>Next step</h3>
        <p className="review-current-stage">{current.label}</p>
        <p>{current.next_action}</p>
        {!pending ? <button disabled={disabled} onClick={startInChat}>Start in chat <Icon name="chevronRight"/></button> : null}
      </section>
      {pending ? <div className="recommendation">
        <h4>Recommendation: {project.stages.find(stage => stage.id === pending.to_stage)?.label}</h4>
        <p>{pending.rationale}</p>
        <p className="supporting">Your active stage stays {current.label} until you confirm.</p>
        <div className="stage-actions">
          <button className="primary" disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: true })}>Confirm next stage</button>
          <button disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: false })}>Stay here</button>
        </div>
      </div> : null}
      <h3 className="path-title">Thinking Path</h3>
      <div className="path-progress"><strong>{done} of {project.stages.length}</strong> stages completed</div>
      <progress aria-label="Thinking Path progress" max={project.stages.length} value={done}/>
      <ol aria-label="Thinking Path stages" className="stage-list">
        {project.stages.map((stage, index) => {
          const isCurrent = stage.id === current.id;
          const expanded = opened === stage.id;
          const continueLabel = stage.completed ? 'Revisit' : 'Continue';
          return <li key={stage.id} className={isCurrent ? 'current-stage' : ''}>
            <button className="stage-row" aria-current={isCurrent ? 'step' : undefined} aria-expanded={expanded} aria-controls={`stage-work-${stage.id}`} onClick={() => setOpened(expanded ? '' : stage.id)}>
              <span className={`stage-number ${stage.completed ? 'completed' : ''}`} aria-hidden="true">{stage.completed ? <Icon name="check"/> : index + 1}</span>
              <span className="stage-label">{stage.label}{stage.completed ? <span className="sr-only"> (completed)</span> : null}</span>
              <Icon name={expanded ? 'chevronDown' : 'chevronRight'}/>
            </button>
            <section hidden={!expanded} id={`stage-work-${stage.id}`} className="stage-work" aria-label={`${stage.label} saved work`}>
              {!isCurrent ? <p>{stage.next_action}</p> : null}
              {!isCurrent && !stage.selectable ? <p className="supporting">Stage unavailable</p> : null}
              {!isCurrent && stage.selectable ? <button className="stage-continue" aria-label={`${continueLabel} ${stage.label}`} disabled={disabled}
                onClick={() => void decide('select-stage', { stage_id: stage.id })}>{continueLabel} <Icon name="chevronRight"/></button> : null}
              {expanded ? <details className="review-disclosure">
                <summary>Saved work</summary>
                <StageWork stage={stage}/>
              </details> : null}
            </section>
          </li>;
        })}
      </ol>
    </section>
  </section>;
}


/** Show saved contributions and coach material for a stage. */
function StageWork({ stage }: { stage: Stage }) {
  return <div className="artifact-work">
    {stage.coach_summary ? <section><h4>Coach summary</h4><CoachText text={stage.coach_summary}/></section> : null}
    <section><h4>Your work</h4>
      {stage.student_work.length ? stage.student_work.map(work => <blockquote key={work.message_id}>{work.text}</blockquote>) : <p className="supporting">Work you share in Design coaching will appear here.</p>}
    </section>
    {stage.feedback.length ? <section><details><summary>Saved feedback</summary>{stage.feedback.map(work => <CoachText key={work.message_id} text={work.text}/>)}</details></section> : null}
  </div>;
}

/** Give each feedback group a short preview and keep further items available. */
function ReviewFeedbackSection({ title, groups, stages, currentStage }: {
  title: string; groups: ReviewFeedback[]; stages: Stage[]; currentStage: string;
}) {
  const populated = groups.filter(group => group.items.length);
  const featured = populated.find(group => group.stage_id === currentStage) ?? populated[populated.length - 1];
  const hasMore = populated.length > 1 || (featured?.items.length ?? 0) > 1;
  return <section className="review-section">
    <h3>{title}</h3>
    {featured ? <p className="review-feedback-preview">{featured.items[0]}</p> : <p className="supporting">No feedback yet.</p>}
    {hasMore ? <details className="review-disclosure">
      <summary>{title === 'Strengths' ? 'More strengths' : 'More areas to improve'}</summary>
      <ul className="review-feedback">
        {populated.map(group => {
          const items = group === featured ? group.items.slice(1) : group.items;
          return items.length ? <li key={group.stage_id}>
            <h4>{stages.find(stage => stage.id === group.stage_id)?.label}</h4>
            <ul>{items.map(item => <li key={item}>{item}</li>)}</ul>
          </li> : null;
        })}
      </ul>
    </details> : null}
  </section>;
}

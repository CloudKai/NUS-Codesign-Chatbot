/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useRef, useState, type ReactNode } from 'react';
import type { Project, ReviewFeedback, Stage } from './api';
import { CoachText } from './CoachText';
import { Icon } from './Icon';
import { buildScaffold, improveScaffold, practiceScaffold, skillExplanation, skillLevel, skillSummary } from './coachingContent';

const reviewTabs = ['Summary', 'Progression'] as const;

/** Show saved feedback and the explicit Thinking Path actions for this chat. */
export function ThinkingPath({ project, disabled, act, startInChat, onClose, status, children, insertScaffold, initialTab }: {
  project: Project; disabled: boolean; insertScaffold: (text: string, switchTo?: 'project') => void; initialTab?: (typeof reviewTabs)[number]; act: (route: string, body: object) => Promise<void>;
  startInChat: () => void; onClose: () => void; status: string; children: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<(typeof reviewTabs)[number]>(
    initialTab ?? (project.pending ? 'Progression' : 'Summary'),
  );
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [opened, setOpened] = useState('');
  const current = project.stages.find(stage => stage.id === project.current_stage)!;
  const done = project.stages.filter(stage => stage.completed).length;
  const pending = project.pending;
  const review = project.review;
  const scores = review?.facione_scores ?? [];
  const skills = skillSummary(scores);
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
      <ReviewFeedbackSection title="Strengths" groups={review?.strengths ?? []} stages={project.stages} currentStage={current.id}
        action="Build on this" onAct={item => insertScaffold(buildScaffold(item), 'project')}/>
      <ReviewFeedbackSection title="Areas to improve" groups={review?.improvements ?? []} stages={project.stages} currentStage={current.id}
        action="Work on this" onAct={item => insertScaffold(improveScaffold(item), 'project')}/>
      <section className="review-section" aria-labelledby="review-facione">
        <h3 id="review-facione">How your idea scores</h3>
        <p className="supporting">These scores are feedback on your critical thinking. They are not a grade.</p>
        {skills ? <div className="skill-highlights">
          {skills.strongest !== skills.grow ? <div className="skill-tile strong">
            <span className="skill-tile-label">Strongest</span>
            <strong>{skills.strongest}</strong>
            <span className="skill-tile-score">{skillLevel(skills.strongestScore)} · {skills.strongestScore}/4</span>
          </div> : null}
          <div className="skill-tile grow">
            <span className="skill-tile-label">{skills.strongest !== skills.grow ? 'Grow next' : 'Keep building'}</span>
            <strong>{skills.grow}</strong>
            <span className="skill-tile-score">{skillLevel(skills.growScore)} · {skills.growScore}/4</span>
            <button disabled={disabled} onClick={() => insertScaffold(practiceScaffold(skills.grow), 'project')}>Practice this</button>
          </div>
        </div> : <p className="skill-empty">Your skill scores will appear here as you share your thinking with the coach.</p>}
        {scores.length ? skills ? <ul className="skill-list">
          {scores.map(item => <li key={item.dimension} className="skill-row" data-unassessed={item.score === null || undefined}>
            <div className="skill-head">
              <strong>{item.dimension}</strong>
              {item.score === null ? <span className="skill-value"><span aria-hidden="true">–</span><span className="sr-only">Not yet assessed</span></span>
                : <span className="skill-value"><span className="skill-level">{skillLevel(item.score)}</span> {item.score}/4</span>}
            </div>
            <div className="skill-pips" aria-hidden="true">{[1, 2, 3, 4].map(step => <span key={step} data-on={(item.score ?? 0) >= step || undefined}/>)}</div>
            {skillExplanation(item.dimension) ? <p className="skill-note">{skillExplanation(item.dimension)}</p> : null}
          </li>)}
        </ul> : <details className="review-disclosure">
          <summary>The six skills</summary>
          <ul className="skill-glossary">
            {scores.map(item => <li key={item.dimension}><strong>{item.dimension}</strong>{skillExplanation(item.dimension) ? <span>{skillExplanation(item.dimension)}</span> : null}</li>)}
          </ul>
        </details> : null}
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
              <span className="stage-label">{stage.label}{stage.completed ? <span className="sr-only"> (completed)</span> : null}
                <small className="stage-count">{stage.student_work.length} {stage.student_work.length === 1 ? 'contribution' : 'contributions'}</small></span>
              <Icon name={expanded ? 'chevronDown' : 'chevronRight'}/>
            </button>
            <section hidden={!expanded} id={`stage-work-${stage.id}`} className="stage-work" aria-label={`${stage.label} saved work`}>
              {!isCurrent ? <p>{stage.next_action}</p> : null}
              {!isCurrent && !stage.selectable ? <p className="supporting">Stage unavailable</p> : null}
              {!isCurrent && stage.selectable ? <button className="stage-continue" aria-label={`${continueLabel} ${stage.label}`} disabled={disabled}
                onClick={() => void decide('select-stage', { stage_id: stage.id })}>{continueLabel} <Icon name="chevronRight"/></button> : null}
              {expanded ? <StageWork stage={stage}/> : null}
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
function ReviewFeedbackSection({ title, groups, stages, currentStage, action, onAct }: {
  title: string; groups: ReviewFeedback[]; stages: Stage[]; currentStage: string; action: string; onAct: (item: string) => void;
}) {
  const act = (item: string) => <button className="scaffold-action" aria-label={`${action}: ${item}`} onClick={() => onAct(item)}>{action}</button>;
  const populated = groups.filter(group => group.items.length);
  const featured = populated.find(group => group.stage_id === currentStage) ?? populated[populated.length - 1];
  const hasMore = populated.length > 1 || (featured?.items.length ?? 0) > 1;
  return <section className="review-section">
    <h3>{title}</h3>
    {featured ? <div className="feedback-item"><p className="review-feedback-preview">{featured.items[0]}</p>{act(featured.items[0])}</div> : <p className="supporting">No feedback yet.</p>}
    {hasMore ? <details className="review-disclosure">
      <summary>{title === 'Strengths' ? 'More strengths' : 'More areas to improve'}</summary>
      <ul className="review-feedback">
        {populated.map(group => {
          const items = group === featured ? group.items.slice(1) : group.items;
          return items.length ? <li key={group.stage_id}>
            <h4>{stages.find(stage => stage.id === group.stage_id)?.label}</h4>
            <ul>{items.map(item => <li key={item} className="feedback-item"><span>{item}</span>{act(item)}</li>)}</ul>
          </li> : null;
        })}
      </ul>
    </details> : null}
  </section>;
}

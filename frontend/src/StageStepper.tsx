/** Five-step Thinking Path indicator built only from API stage data. */
import type { Project, Stage } from './api';
import { Icon } from './Icon';

/** True once the chat has saved project work, a completed stage, or a pending stage decision. */
export function hasProjectWork(project: Pick<Project, 'stages' | 'pending'>) {
  return !!project.pending || project.stages.some(stage => stage.completed || stage.student_work.length > 0);
}

export function StageStepper({ stages, currentStage, pending, onOpen, compact = false }: {
  stages: Pick<Stage, 'id' | 'label' | 'completed'>[]; currentStage: string; pending: boolean;
  onOpen?: () => void; compact?: boolean;
}) {
  const index = Math.max(0, stages.findIndex(stage => stage.id === currentStage));
  const current = stages[index];
  const done = stages.filter(stage => stage.completed).length;
  const description = `Thinking Path: step ${index + 1} of ${stages.length}, ${current?.label ?? ''}. ${done} completed.`;
  const steps = <>
    <span className="stepper-dots" aria-hidden="true">
      {stages.map((stage, position) => <span key={stage.id}
        className={`stepper-dot ${stage.completed ? 'done' : ''} ${position === index ? 'current' : ''}`}>
        {stage.completed ? <Icon name="check"/> : null}
      </span>)}
    </span>
    {current ? <span className="stepper-label" aria-hidden="true">{current.label}</span> : null}
    {pending ? <span className="decision-dot" aria-hidden="true"/> : null}
  </>;
  if (onOpen) {
    return <button className={`stepper ${compact ? 'compact' : ''}`} onClick={onOpen}
      aria-label={`${description} Open progression.`} title="Open progression"
      aria-description={pending ? 'A stage decision is pending' : undefined}>{steps}</button>;
  }
  return <div className={`stepper ${compact ? 'compact' : ''}`} role="img"
    aria-label={`${description}${pending ? ' A stage decision is pending.' : ''}`}>{steps}</div>;
}

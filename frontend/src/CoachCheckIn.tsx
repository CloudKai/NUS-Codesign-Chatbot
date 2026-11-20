/** One deterministic coach check-in above the composer. It is never saved as a message. */
import type { CheckIn } from './coachingContent';
import { Icon } from './Icon';

export function CoachCheckIn({ checkIn, onAct, onDismiss }: {
  checkIn: CheckIn; onAct: (checkIn: CheckIn) => void; onDismiss: (checkIn: CheckIn) => void;
}) {
  return <section className="check-in" aria-label="Coach check-in">
    <span className="check-in-icon" aria-hidden="true"><Icon name="coach"/></span>
    <div className="check-in-body">
      <strong>From your coach</strong>
      <p>{checkIn.message}</p>
    </div>
    <div className="check-in-actions">
      <button className="primary" onClick={() => onAct(checkIn)}>{checkIn.action}</button>
      <button className="icon-button" aria-label="Dismiss check-in" title="Dismiss" onClick={() => onDismiss(checkIn)}><Icon name="close"/></button>
    </div>
  </section>;
}

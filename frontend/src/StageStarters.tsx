/** Stage-aware starter chips above the composer. Chips insert editable scaffolds only. */
import { useState } from 'react';
import { starterChips } from './coachingContent';
import { Icon } from './Icon';

export function StageStarters({ stageId, disabled, collapsed, setCollapsed, onChoose, hintLevel, onHint }: {
  stageId: string; disabled: boolean; collapsed: boolean; setCollapsed: (value: boolean) => void; onChoose: (text: string) => void;
  hintLevel: number; onHint: () => void;
}) {
  const [more, setMore] = useState(false);
  const chips = starterChips(stageId).slice(0, 2);
  if (collapsed) return <div className="stage-starters collapsed">
    <button className="starter-toggle-visible" onClick={() => setCollapsed(false)}>Show suggestions</button>
  </div>;
  return <section className={`stage-starters ${more ? 'more' : ''}`} aria-label="Suggestions for this stage">
    <div className="stage-chips">
      <button className="hint-chip" disabled={disabled} onClick={onHint}><Icon name="spark"/>{hintLevel > 0 ? 'Stronger hint' : 'Need a hint?'}</button>
      {chips.map((chip, index) => <button key={chip.label} className={index > 0 ? 'extra-chip' : undefined} disabled={disabled} onClick={() => onChoose(chip.text)}>{chip.label}</button>)}
    </div>
    <button className="chips-more" aria-expanded={more} onClick={() => setMore(value => !value)}>{more ? 'Fewer' : 'More'}</button>
    <button className="chips-hide" onClick={() => setCollapsed(true)}>Hide</button>
  </section>;
}

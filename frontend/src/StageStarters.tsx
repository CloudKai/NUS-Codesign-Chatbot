/** Stage-aware starter chips above the composer. Chips insert editable scaffolds only. */
import { useState } from 'react';
import { starterChips } from './coachingContent';

export function StageStarters({ stageId, disabled, collapsed, setCollapsed, onChoose }: {
  stageId: string; disabled: boolean; collapsed: boolean; setCollapsed: (value: boolean) => void; onChoose: (text: string) => void;
}) {
  const [more, setMore] = useState(false);
  const chips = starterChips(stageId).slice(0, 3);
  if (collapsed) return <div className="stage-starters collapsed">
    <button className="starter-toggle-visible" onClick={() => setCollapsed(false)}>Show suggestions</button>
  </div>;
  return <section className={`stage-starters ${more ? 'more' : ''}`} aria-label="Suggestions for this stage">
    <div className="stage-chips">
      {chips.map((chip, index) => <button key={chip.label} className={index > 0 ? 'extra-chip' : undefined} disabled={disabled} onClick={() => onChoose(chip.text)}>{chip.label}</button>)}
    </div>
    <button className="chips-more" aria-expanded={more} onClick={() => setMore(value => !value)}>{more ? 'Fewer' : 'More'}</button>
    <button className="chips-hide" onClick={() => setCollapsed(true)}>Hide</button>
  </section>;
}

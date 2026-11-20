import { useState } from 'react';
import { Icon } from './Icon';

/** Optional reasoning scaffolds insert editable drafts without making model calls. */
export function ReasoningPrompts({ disabled, onChoose }: { disabled: boolean; onChoose: (prompt: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const prompts = [
    { label: 'Explore a problem', text: 'The problem I want to explore is…\nAsk me questions that help me work out who is affected and what I need to learn about them.', icon: 'path' },
    { label: 'Test an assumption', text: 'One assumption I am making is…\nWhat evidence would challenge it?', icon: 'spark' },
    { label: 'Try another perspective', text: 'From my perspective…\nWho might see this differently, and why?', icon: 'chat' },
    { label: 'Connect to evidence', text: 'My current claim is…\nAsk me questions that help me separate what the sources support from what I am assuming.', icon: 'book' },
  ] as const;
  return <section className="reasoning-prompts" aria-label="Reasoning starters">
    <div className={`prompt-options ${expanded ? 'starters-expanded' : ''}`} id="reasoning-options">
      {prompts.map((prompt, index) => <button className={index > 1 ? 'extra-starter' : undefined} key={prompt.label} disabled={disabled} onClick={() => onChoose(prompt.text)}><Icon name={prompt.icon}/>{prompt.label}</button>)}
    </div>
    <button className="starter-toggle" aria-expanded={expanded} aria-controls="reasoning-options" onClick={() => setExpanded(value => !value)}>{expanded ? 'Fewer starters' : 'All starters'}<Icon name={expanded ? 'chevronRight' : 'chevronDown'}/></button>
  </section>;
}

/** Two-option segmented control with native radio semantics and arrow-key support. */
export function ModeSwitch({ value, onChange, disabled }: {
  value: 'lecture' | 'project'; onChange: (value: 'lecture' | 'project') => void; disabled: boolean;
}) {
  const options = [
    { id: 'lecture', label: 'Lecture help', short: 'Lecture' },
    { id: 'project', label: 'Design coaching', short: 'Design' },
  ] as const;
  return <div className="composer-mode">
    <fieldset className="mode-switch" disabled={disabled}
      title="Lecture help keeps your project stage unchanged. Design coaching develops your saved project.">
      <legend className="sr-only">Conversation mode</legend>
      {options.map(option => <label key={option.id}>
        <input type="radio" name="conversation-mode" value={option.id} checked={value === option.id}
          onChange={() => onChange(option.id)}/>
        <span><span className="mode-long">{option.label}</span><span className="mode-short" aria-hidden="true">{option.short}</span></span>
      </label>)}
    </fieldset>
  </div>;
}

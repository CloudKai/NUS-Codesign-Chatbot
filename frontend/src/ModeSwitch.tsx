/** Two-option segmented control with native radio semantics and arrow-key support. */
export function ModeSwitch({ value, onChange, disabled }: {
  value: 'improve' | 'project'; onChange: (value: 'improve' | 'project') => void; disabled: boolean;
}) {
  const options = [
    { id: 'improve', label: 'Improve my design', short: 'Improve' },
    { id: 'project', label: 'Design coaching', short: 'Design' },
  ] as const;
  return <div className="composer-mode">
    <fieldset className="mode-switch" disabled={disabled}
      title="Improve my design gives feedback on an existing design. Design coaching follows the Thinking Path.">
      <legend className="sr-only">Conversation mode</legend>
      {options.map(option => <label key={option.id}>
        <input type="radio" name="conversation-mode" value={option.id} checked={value === option.id}
          onChange={() => onChange(option.id)}/>
        <span><span className="mode-long">{option.label}</span><span className="mode-short" aria-hidden="true">{option.short}</span></span>
      </label>)}
    </fieldset>
  </div>;
}

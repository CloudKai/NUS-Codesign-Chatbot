/** Two-option segmented control with native radio semantics and arrow-key support. */
export function ModeSwitch({ value, onChange, disabled }: {
  value: 'lecture' | 'project'; onChange: (value: 'lecture' | 'project') => void; disabled: boolean;
}) {
  const options = [
    { id: 'lecture', label: 'Lecture help' },
    { id: 'project', label: 'Design coaching' },
  ] as const;
  return <div className="composer-mode">
    <fieldset className="mode-switch" disabled={disabled}
      title="Lecture help keeps your project stage unchanged. Design coaching develops your saved project.">
      <legend className="sr-only">Conversation mode</legend>
      {options.map(option => <label key={option.id}>
        <input type="radio" name="conversation-mode" value={option.id} checked={value === option.id}
          onChange={() => onChange(option.id)}/>
        <span>{option.label}</span>
      </label>)}
    </fieldset>
  </div>;
}

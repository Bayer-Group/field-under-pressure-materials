/** A labelled group of toggle buttons (`.segmented`); each button sets aria-pressed itself. */
export function Choice({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="choice" role="group" aria-label={label}>
      <span className="choice-label">{label}</span>
      <div className="segmented">{children}</div>
    </div>
  )
}

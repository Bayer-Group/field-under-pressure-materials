/** A labelled group of toggle buttons (`.seg-buttons`); each button sets aria-pressed itself. */
export function Choice({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="choice" role="group" aria-label={label}>
      <span className="choice-label">{label}</span>
      <div className="seg-buttons">{children}</div>
    </div>
  )
}

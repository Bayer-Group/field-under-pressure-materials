import { useId, useRef, useState, type CSSProperties } from 'react'

const TIP_WIDTH = 280 // px, matches .genus-tip max-width
const ROOM_ABOVE = 110 // px a two-sentence tip needs above the name; less than this and it opens below

/** A genus name; with a description it is focusable and shows the description in a tooltip on hover and focus
 *  (Escape closes it). Without one it is plain text. The tip is positioned against the viewport (fixed), so the
 *  scrolling panels it sits in cannot clip it. */
export function GenusName({ name, description }: { name: string; description: string | null | undefined }) {
  const tipId = useId()
  const [pos, setPos] = useState<CSSProperties | null>(null)
  const wrap = useRef<HTMLSpanElement>(null)
  const show = () => {
    const r = wrap.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.max(8, Math.min(r.left, window.innerWidth - TIP_WIDTH - 8))
    setPos(r.top < ROOM_ABOVE ? { left, top: r.bottom + 6 } : { left, bottom: window.innerHeight - r.top + 6 })
  }
  const hide = () => setPos(null)
  if (!description) return <>{name}</>
  return (
    <span ref={wrap} className="genus-wrap" onPointerEnter={show} onPointerLeave={hide}>
      <span className="genus-name" tabIndex={0} aria-describedby={tipId}
        onFocus={show} onBlur={hide}
        onKeyDown={(e) => { if (e.key === 'Escape') hide() }}>{name}</span>
      <span role="tooltip" id={tipId} className={`genus-tip ${pos ? 'open' : ''}`} style={pos ?? undefined}>{description}</span>
    </span>
  )
}

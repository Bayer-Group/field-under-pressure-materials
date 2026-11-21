// Before/after wipe between two crops of GUI screenshots, with a handle the presenter can drag.
//
//   <div class="wipe" data-prevent-swipe data-under="greenness:map" data-over="greenness-map:map" data-height="820">
//
// data-under / data-over: "<shot>:<rect key>[:index]" crops from shots/rects.json.
// On entry the handle sweeps across once and settles in the middle.
Deck.anim('wipe', (slide) => {
  const box = slide.querySelector('.wipe')
  const under = box.querySelector('.under'), over = box.querySelector('.over'), handle = box.querySelector('.handle')

  Deck.once(slide, 'wipe', () => {
    const H = +(box.dataset.height ?? 800)
    const crop = (layer, spec) => {
      const [shot, key, i = 0] = spec.split(':')
      const r = Deck.rect(shot, key, +i) ?? [0, 0, 2400, 1350]
      const s = H / r[3]
      Object.assign(layer.style, {
        backgroundImage: `url(${Deck.shot(shot)})`,
        backgroundSize: `${2400 * s}px ${1350 * s}px`,
        backgroundPosition: `${-r[0] * s}px ${-r[1] * s}px`,
      })
      return r[2] * s
    }
    const w = Math.min(crop(under, box.dataset.under), crop(over, box.dataset.over))
    box.style.width = `${w}px`
    box.style.height = `${H}px`
  })

  const { w } = Deck.size(box)
  const pos = { p: 0.5 }
  const render = () => {
    over.style.clipPath = `inset(0 0 0 ${pos.p * 100}%)`
    gsap.set(handle, { x: pos.p * w })
  }

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading, .sub'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(box, { scale: 0.92, autoAlpha: 0, duration: 0.9 }, 0.1)
    .fromTo(pos, { p: 1 }, { p: 0, duration: 1.2, ease: 'power2.inOut', onUpdate: render, immediateRender: true })
    .to(pos, { p: 0.5, duration: 0.9, ease: 'power2.inOut', onUpdate: render })
    .from(box.querySelectorAll('.tag'), { autoAlpha: 0, y: 12, duration: 0.4, stagger: 0.1 }, '-=0.3')
  render()

  // Dragging works in slide pixels even though reveal scales the slide.
  Draggable.create(handle, {
    type: 'x',
    bounds: { minX: 0, maxX: w },
    onPress() {
      tl.progress(1)
    },
    onDrag() {
      pos.p = this.x / w
      over.style.clipPath = `inset(0 0 0 ${pos.p * 100}%)`
    },
  })
  return tl
})

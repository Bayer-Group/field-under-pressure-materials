// Nitrogen cycle drawn from DeckData.ncycle: one click per process, then nitrogen flows round the loop.
// Steps: one per process, then the DNRA shortcut.
Deck.anim('ncycle', (slide) => {
  const svg = slide.querySelector('svg.cycle')
  const S = 1000, C = S / 2, RAD = 330, GAP = 17
  const N = DeckData.ncycle
  const node = Object.fromEntries(N.nodes.map((n) => [n.id, n]))
  const pt = (deg, r = RAD) => [C + Math.cos((deg * Math.PI) / 180) * r, C + Math.sin((deg * Math.PI) / 180) * r]
  const toAngle = (a, b) => (b <= a ? b + 360 : b)

  Deck.once(slide, 'cycle', () => {
    svg.setAttribute('viewBox', `0 0 ${S} ${S}`)
    let s = `<defs><marker id="nc-arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z"/></marker></defs>`
    s += `<path id="nc-ring" class="ring" d="M${C},${C - RAD} a${RAD},${RAD} 0 1,1 0,${2 * RAD} a${RAD},${RAD} 0 1,1 0,${-2 * RAD}"/>`
    N.processes.forEach((p, i) => {
      const a0 = node[p.from].angle + GAP, a1 = toAngle(node[p.from].angle, node[p.to].angle) - GAP
      const [x0, y0] = pt(a0), [x1, y1] = pt(a1)
      const mid = (a0 + a1) / 2, [lx, ly] = pt(mid, RAD + 95)
      const anchor = Math.abs(Math.cos((mid * Math.PI) / 180)) < 0.3 ? 'middle' : Math.cos((mid * Math.PI) / 180) > 0 ? 'start' : 'end'
      s += `<g class="proc" data-i="${i}">
        <path class="arc" d="M${x0},${y0} A${RAD},${RAD} 0 0,1 ${x1},${y1}" marker-end="url(#nc-arrow)"/>
        <text x="${lx}" y="${ly}" text-anchor="${anchor}"><tspan class="pname">${p.name}</tspan><tspan class="genes" x="${lx}" dy="38">${p.genes}</tspan></text></g>`
    })
    const sc = N.shortcut
    const [sx, sy] = pt(node[sc.from].angle, RAD - 70), [ex, ey] = pt(node[sc.to].angle, RAD - 70)
    s += `<g class="proc shortcut"><path class="arc" d="M${sx},${sy} Q${C + 60},${C + 60} ${ex},${ey}" marker-end="url(#nc-arrow)"/>
      <text x="${C + 40}" y="${C + 10}" text-anchor="middle"><tspan class="pname">${sc.name}</tspan><tspan class="genes" x="${C + 40}" dy="34">${sc.genes}</tspan></text></g>`
    N.nodes.forEach((n) => {
      const [x, y] = pt(n.angle)
      s += `<g class="node" transform="translate(${x},${y})"><circle r="62"/><text dy="14" text-anchor="middle">${n.label}</text></g>`
    })
    s += '<g class="flow">' + '<circle r="9"/>'.repeat(6) + '</g>'
    svg.innerHTML = s
  })

  const procs = svg.querySelectorAll('.proc:not(.shortcut)')
  const flow = svg.querySelectorAll('.flow circle')

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading, .sub'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(svg.querySelectorAll('.node'), { scale: 0, transformOrigin: '50% 50%', duration: 0.6, ease: 'back.out(2)', stagger: 0.12 }, 0.2)
  gsap.set(svg.querySelectorAll('.arc'), { drawSVG: 0 })
  gsap.set(svg.querySelectorAll('.proc text'), { autoAlpha: 0 })
  gsap.set(flow, { autoAlpha: 0 })

  const showProc = (g, at) => {
    tl.addLabel(at)
      .to(g.querySelector('.arc'), { drawSVG: '100%', duration: 0.9, ease: 'power2.inOut' }, at)
      .fromTo(g.querySelector('text'), { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.5 }, `${at}+=0.5`)
  }
  procs.forEach((g, i) => showProc(g, `step${i + 1}`))
  tl.to(flow, { autoAlpha: 1, duration: 0.5, stagger: 0.08 }, '+=0.1')
  showProc(svg.querySelector('.shortcut'), `step${procs.length + 1}`)

  // Nitrogen "particles" circling the ring (decorative loop; only visible once the loop closes).
  Deck.loop(() =>
    flow.forEach((c, i) =>
      gsap.to(c, {
        motionPath: { path: '#nc-ring', align: '#nc-ring', alignOrigin: [0.5, 0.5], start: i / flow.length, end: i / flow.length + 1 },
        duration: 9,
        ease: 'none',
        repeat: -1,
      }),
    ),
  )
  return tl
})

// A spinning Earth drawn on a <canvas> in the logo's greens, so the globe in the lockup can turn on
// its axis. Uses d3-geo's orthographic projection and the world-atlas land outlines (vendor/geo/).
//
//   const earth = Deck.earth(canvas)                    // draws once
//   gsap.to(earth, { lon: '-=360', duration: 40, ease: 'none', repeat: -1, onUpdate: earth.draw })
;(function () {
  'use strict'
  const land = topojson.feature(window.LAND_TOPO, window.LAND_TOPO.objects.land)
  const C = {
    oceanLight: '#45c98f', ocean: '#10a16a', oceanDeep: '#00653f',
    land: '#5fdca5', landLight: '#a2ecca',
  }

  /** lon: the longitude facing the viewer; lat: how far the north pole leans towards the viewer. */
  Deck.earth = function (canvas, { lon = -30, lat = 18 } = {}) {
    const css = Deck.size(canvas).w || 200
    const ratio = Math.min(3, Math.max(2, (window.devicePixelRatio || 1) * (Reveal.getScale?.() || 1)))
    const px = Math.round(css * ratio)
    canvas.width = canvas.height = px
    const ctx = canvas.getContext('2d')
    const r = px / 2 - 1
    const projection = d3.geoOrthographic().translate([px / 2, px / 2]).scale(r).clipAngle(90).precision(0.3)
    const path = d3.geoPath(projection, ctx)

    // Fixed lighting, like the logo: lit from the top left, darker towards the bottom right.
    const ocean = ctx.createRadialGradient(px * 0.32, px * 0.26, 0, px * 0.5, px * 0.5, r * 1.05)
    ocean.addColorStop(0, C.oceanLight)
    ocean.addColorStop(0.55, C.ocean)
    ocean.addColorStop(1, C.oceanDeep)
    const landFill = ctx.createRadialGradient(px * 0.3, px * 0.24, 0, px * 0.5, px * 0.5, r * 1.05)
    landFill.addColorStop(0, C.landLight)
    landFill.addColorStop(0.5, C.land)
    landFill.addColorStop(1, '#2fbf82')
    const shade = ctx.createRadialGradient(px * 0.5, px * 0.5, r * 0.55, px * 0.5, px * 0.5, r)
    shade.addColorStop(0, 'rgba(0,40,25,0)')
    shade.addColorStop(1, 'rgba(0,40,25,0.28)')

    const earth = {
      lon,
      lat,
      draw() {
        projection.rotate([-earth.lon, -earth.lat, 0])
        ctx.clearRect(0, 0, px, px)
        ctx.beginPath()
        ctx.arc(px / 2, px / 2, r, 0, Math.PI * 2)
        ctx.fillStyle = ocean
        ctx.fill()
        ctx.beginPath()
        path(land)
        ctx.fillStyle = landFill
        ctx.fill()
        ctx.beginPath()
        ctx.arc(px / 2, px / 2, r, 0, Math.PI * 2)
        ctx.fillStyle = shade
        ctx.fill()
      },
    }
    earth.draw()
    return earth
  }
})()

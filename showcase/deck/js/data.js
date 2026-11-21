// Content the animations read. Edit here rather than inside the animation files.
// Anything marked ILLUSTRATIVE is placeholder data: replace it with real numbers before presenting.
window.DeckData = {
  // Slide "Everything links to the sampling event": one chip per data source, laid out on a ring.
  sources: [
    { name: 'NEON', what: 'field sites, soil cores' },
    { name: 'NMDC', what: 'soil metagenomes' },
    { name: 'SSURGO', what: 'soil survey' },
    { name: 'Daymet', what: 'daily weather' },
    { name: 'CDL', what: 'crop history' },
    { name: 'Sentinel-2 / Landsat', what: 'greenness' },
    { name: 'NAIP / NEON camera', what: 'aerial photos' },
    { name: '3DEP', what: 'terrain' },
  ],

  // Slide "Two sites, 29 plots".
  sites: [
    { name: 'North Sterling, CO', code: 'STER', plots: 19, tag: 'dryland' },
    { name: 'Konza Prairie, KS', code: 'KONA', plots: 10, tag: 'prairie farm' },
  ],

  // Slide "Greenness over time". ILLUSTRATIVE: one synthetic growing season.
  // Replace with a real export, e.g. one plot-year of satellite readings as { day, ndvi } pairs.
  greenness: (() => {
    const curve = (d) => 0.17 + 0.62 / (1 + Math.exp(-(d - 150) / 11)) - 0.6 / (1 + Math.exp(-(d - 232) / 10))
    let seed = 7
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    const readings = []
    for (let d = 95; d <= 300; d += 4 + Math.floor(rnd() * 7)) {
      readings.push({ day: d, ndvi: Math.max(0.05, curve(d) + (rnd() - 0.5) * 0.08) })
    }
    return {
      dayRange: [90, 305],
      curve,
      readings,
      visits: [128, 176, 214], // soil sampling visits (day of year)
    }
  })(),

  // Slide "Nitrogen cycle": nodes clockwise from the top, then the processes between them.
  // Gene names follow rules/ko_panel.csv.
  ncycle: {
    nodes: [
      { id: 'n2', label: 'N₂', angle: -90 },
      { id: 'nh4', label: 'NH₄⁺', angle: 0 },
      { id: 'no3', label: 'NO₃⁻', angle: 90 },
      { id: 'n2o', label: 'N₂O', angle: 180 },
    ],
    processes: [
      { from: 'n2', to: 'nh4', name: 'Fixation', genes: 'nifH · nifD · nifK' },
      { from: 'nh4', to: 'no3', name: 'Nitrification', genes: 'amoA · hao · nxrB' },
      { from: 'no3', to: 'n2o', name: 'Denitrification', genes: 'narG · napA · nirK/S · norB' },
      { from: 'n2o', to: 'n2', name: 'N₂O reduction', genes: 'nosZ' },
    ],
    shortcut: { from: 'no3', to: 'nh4', name: 'DNRA', genes: 'nrfA · nirB' },
  },
}

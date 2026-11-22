# Terranos showcase video (62 s, written in code)

Output: `terranos-showcase.mp4` (1920×1080, 30 fps, H.264 + AAC).

| File | What it does |
|---|---|
| `capture.mjs` | Drives the running GUI in headless Chromium, saves real screens to `shots/` and the positions of key elements to `shots/rects.js` |
| `video.html` | The video itself. Every frame is a pure function of time (`seek(t)`). Open it in a browser to preview: Space pauses, ←/→ step a frame, click the bar to scrub, `?t=12` starts at 12 s |
| `music.mjs` | Synthesizes the soundtrack (120 bpm; groove for the app tour, a half-time build for the data break, playful / sad / happy sections and sound effects for the corn story, whooshes on every wipe) |
| `render.mjs` | Steps `seek()` through all 1,860 frames and pipes them into ffmpeg with the soundtrack |
| `cdp.mjs` | Minimal Chrome DevTools Protocol client (no npm dependencies) |

Rebuild (needs `chromium`, `ffmpeg`, Node ≥ 22, and the GUI running with a current `web/dist` and a server started after the Roles and treatment plan routes were added):

```bash
node showcase/capture.mjs http://127.0.0.1:8000
node showcase/render.mjs                         # ~3–4 min
node showcase/render.mjs --stills 5,10.5,20      # quick PNG checks in showcase/stills/
```

Storyboard (all app screens are plot STER_010):

| Time | Scene |
|---|---|
| 0–4 s | Title card: the logo builds, then the tagline |
| 4–10 s | 01 Plot selection: zoom the map to North Sterling, hover a plot in the list (it lights up on the map), open it |
| 10–14 s | 02 Soil microbes, taxonomy: phylum bar and table |
| 14–18 s | 02 Soil microbes, roles: role classes, then the role tree (pest suppressors vs. plant pathogens) |
| 18–24 s | 03 Soil characteristics: the cards fly out of the window, status tags glow |
| 24–32 s | Break: a DNA double helix (biological data) and stacked map layers (geoinformatic data) stream into the Terranos globe; out come the app's five tabs |
| 32–38 s | 04 Crop disease risk: the heatmap fills in, this plot's row and its corn cell |
| 38–56 s | Break, the corn story: a farmer plants corn; it shoots up and startles him; a Terranos greenness card shows the plot browning and the chart plunging; the corn is ill (thermometer, storm cloud); he opens the Treatment plan on his phone and taps "Buy now"; the parcel lands, the sky clears and both jump for joy |
| 56–62 s | End card |

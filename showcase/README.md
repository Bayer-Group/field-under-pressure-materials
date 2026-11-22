# Terranos showcase video (66 s, written in code)

Output: `terranos-showcase.mp4` (1920×1080, 30 fps, H.264 + AAC).

| File | What it does |
|---|---|
| `capture.mjs` | Drives the running GUI in headless Chromium, saves real screens to `shots/` and the positions of key elements to `shots/rects.js` |
| `video.html` | The video itself. Every frame is a pure function of time (`seek(t)`). Open it in a browser to preview: Space pauses, ←/→ step a frame, click the bar to scrub, `?t=12` starts at 12 s |
| `music.mjs` | Synthesizes the soundtrack (120 bpm; groove for the app tour, a half-time build for the data break, playful / sad / happy sections and sound effects for the two-neighbours story, whooshes on every wipe) |
| `render.mjs` | Steps `seek()` through all 1,980 frames and pipes them into ffmpeg with the soundtrack |
| `cdp.mjs` | Minimal Chrome DevTools Protocol client (no npm dependencies) |

Rebuild (needs `chromium`, `ffmpeg`, Node ≥ 22, and the GUI running with a current `web/dist` and a server started after the Roles and treatment plan routes were added):

```bash
node showcase/capture.mjs http://127.0.0.1:8000
node showcase/render.mjs                         # ~3–4 min
node showcase/render.mjs --stills 5,10.5,20      # quick PNG checks in showcase/stills/
```

Storyboard (all app screens are plot STER_010). There are no logo cards: the video opens on the app and ends on the story. Each app section freezes for 2 s once its view is fully loaded, so it can be read; `HOLDS` in `video.html` (and the same list in `music.mjs`) sets where.

| Time | Scene |
|---|---|
| 0–6 s | 01 Plot selection: zoom the map to North Sterling, hover a plot in the list (it lights up on the map; hold), open it |
| 6–12.6 s | 02 Soil microbes, taxonomy: phylum bar and table (hold on the table) |
| 12.6–18.8 s | 02 Soil microbes, roles: role classes, then the role tree, pest suppressors vs. plant pathogens (hold) |
| 18.8–28 s | 03 Soil characteristics: the cards fly out of the window, status tags glow (hold) |
| 28–36 s | Break: a DNA double helix (biological data) and stacked map layers (geoinformatic data) stream into the Terranos globe; out come the app's five tabs |
| 36–44 s | 04 Crop disease risk: the crop names, then the heatmap fills in, this plot's row and its corn cell (hold on the heatmap) |
| 44–66 s | Break, two neighbours: one checks the crop disease risk on his phone (corn higher risk, sugar beet lower risk; a cartoon card, not real STER_010 numbers) and plants (white) sugar beet, which pops up at once and startles him; the other shrugs and plants corn anyway; the camera dives into the soil, where an angry fungus and grumpy bacteria attack the roots and turn them red; back up, red veins climb the corn from its foot and it falls ill (thermometer); his neighbour shows him the app, a light bulb goes on, he opens the Treatment plan and taps "Buy now"; the parcel lands, the corn recovers and everyone jumps for joy |

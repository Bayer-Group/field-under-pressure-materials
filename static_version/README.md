# Static demo (read-only)

A pre-baked snapshot of the GUI's light mode: 5 plots (STER_006, 010, 011, 012, 016). No server, Python or npm needed.

Open `index.html` by double-clicking it, or run `python3 -m http.server -d static_version` and visit http://127.0.0.1:8000.

Data is a fixed snapshot; the map background needs internet for its tiles. Maintainers rebuild it with `bash scripts/bake_static.sh`.

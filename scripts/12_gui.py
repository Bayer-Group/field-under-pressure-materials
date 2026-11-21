"""Start the GUI on this machine: http://127.0.0.1:8000

    cd web && npm install && npm run build      (once, and after changing anything in web/)
    .venv/bin/python scripts/12_gui.py [--port 8000] [--reload]

Serves the local API (src/cropfit/api.py) and the built frontend (web/dist). Local use only: it listens on
127.0.0.1 and has no accounts. For frontend development run this and `npm run dev` in web/ side by side.
"""
import argparse
import socket
import sys
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import uvicorn
from cropfit import api

HOST = "127.0.0.1"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Start the GUI on this machine (127.0.0.1 only).")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart when a file in src/ changes (backend development)")
    args = ap.parse_args()
    with socket.socket() as s:                      # say so plainly instead of a uvicorn traceback
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, args.port))
        except OSError:
            sys.exit(f"Port {args.port} is in use (another GUI may be running): try --port {args.port + 1}")
    if not api.WEB_DIST.exists():
        print("web/dist not found: only the API is served. Build the frontend: cd web && npm install && npm run build")
    if not (api.PROCESSED / "plot_geometry.parquet").exists():
        print(f"No processed data in {api.PROCESSED}: the GUI will start but show an error. "
              "Run the data pipeline first (see AGENT.md).")
    print(f"GUI: http://{HOST}:{args.port}   API docs: http://{HOST}:{args.port}/docs")
    if args.reload:
        uvicorn.run("cropfit.api:app", host=HOST, port=args.port, reload=True, reload_dirs=[str(SRC)])
    else:
        uvicorn.run(api.app, host=HOST, port=args.port)

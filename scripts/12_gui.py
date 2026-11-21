"""Start the GUI on this machine: http://127.0.0.1:8000

    cd web && npm install && npm run build      (once, and after changing anything in web/)
    .venv/bin/python scripts/12_gui.py [--port 8000]

Serves the local API (src/cropfit/api.py) and the built frontend (web/dist). Local use only: it listens on
127.0.0.1 and has no accounts. For frontend development run this and `npm run dev` in web/ side by side.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import uvicorn
from cropfit import api

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    if not api.WEB_DIST.exists():
        print("web/dist not found: only the API is served. Build the frontend: cd web && npm install && npm run build")
    uvicorn.run(api.app, host="127.0.0.1", port=port)

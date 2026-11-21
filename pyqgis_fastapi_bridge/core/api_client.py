# -*- coding: utf-8 -*-
"""
Klient HTTP do komunikacji z API FastAPI.
Wykonywany asynchronicznie w tle przez QgsTask.
"""

import json
import urllib.request
import urllib.error

class BackendApiClient:
    BASE_URL = "http://127.0.0.1:8000/api/v1"

    @classmethod
    def analyze_parcel(cls, parcel_id: str, teryt_id: str = None, lat: float = 52.18, lon: float = 20.76):
        """Wysyła zapytanie analityczne do backendu."""
        params = f"?lat={lat:.4f}&lon={lon:.4f}"
        if teryt_id:
            params += f"&teryt_id={urllib.parse.quote(teryt_id)}"

        url = f"{cls.BASE_URL}/analysis/{parcel_id}{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "PyQgisFastApiBridge/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as e:
            return {
                "parcel_id": parcel_id,
                "status": "OFFLINE_FALLBACK",
                "message": f"Brak połączenia z API (uruchom: python backend/run_backend.py). Błąd: {e}",
                "metrics": {
                    "calculated_area_ha": 10.0,
                    "sample_metric": 1.0
                }
            }

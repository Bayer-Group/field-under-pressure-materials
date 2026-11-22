"""Switch light mode on or off: every download (and the event registry built from it) is restricted to a
few plots, so the whole pipeline runs in a fraction of the time and disk.

Light mode is ON BY DEFAULT: with no data/light_mode.txt (a fresh clone) it uses the default plots,
`light_plots` in config/regions.yaml. Run `off` to download and build all plots.

Usage: 00_light_mode.py [status]              show whether light mode is on and for which plots
       00_light_mode.py on [PLOT ...]         default plots: `light_plots` in config/regions.yaml
       00_light_mode.py off                   all plots (writes "off" to data/light_mode.txt)

Plots can be written "STER_006" or "STER 006". You can also edit data/light_mode.txt by hand: one plot per
line, or a single line "off"; deleting it goes back to the default plots. Run it before the downloads
(pull_nmdc_cropland.py, 02_fetch_neon.py, then the rest of the pipeline in order). Switching it does not delete
anything already downloaded: processed tables are replaced when their step is re-run, and cached satellite
scenes of other plots are ignored, not removed.
"""
import re
import sys
from pathlib import Path

import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import config  # noqa: E402


def status() -> None:
    lp = config.light_plots()
    if lp is None:
        print(f"light mode is OFF (all plots of {', '.join(config.sites())})")
    else:
        how = "" if config.LIGHT_FILE.exists() else " [default: no data/light_mode.txt]"
        print(f"light mode is ON{how}: {len(lp)} plots ({', '.join(lp)}); sites {', '.join(config.sites()) or 'none'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0].lower() if args else "status"
    if cmd == "on":
        raw = " ".join(args[1:]).upper()
        # accepts "STER_006", "STER 006", "STER 006, STER 010" and one plot per argument
        pat = r"([A-Z]{4})[\s_-]*(\d{3})"
        leftover = re.sub(pat, " ", raw).replace(",", " ").split()
        if leftover:
            sys.exit(f"not a plot ID: {leftover[0]!r} (expected e.g. STER_006 or 'STER 006')")
        plots = sorted({f"{a}_{b}" for a, b in re.findall(pat, raw)}) or config.default_light_plots()
        res = pd.read_csv(config.RESOURCES / "neon_soil_plots_landcover.csv")
        unknown = sorted(set(plots) - set(res["plot"].str.replace(".basePlot.bgc", "", regex=False)))
        if unknown:
            print(f"warning: no coordinates in resources/neon_soil_plots_landcover.csv for {', '.join(unknown)}")
        config.LIGHT_FILE.write_text("# light mode: downloads restricted to these plots "
                                     "(scripts/00_light_mode.py off for all plots)\n" + "\n".join(plots) + "\n")
    elif cmd == "off":
        config.LIGHT_FILE.write_text("# light mode is off: all plots are downloaded and built "
                                     "(scripts/00_light_mode.py on, or delete this file, to switch back)\noff\n")
    elif cmd != "status":
        sys.exit(__doc__)
    status()

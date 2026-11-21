"""Pull NEON portal products for STER/KONA, save raw parquet, print table names + row counts.

Usage: 02_fetch_neon.py [--allow-partial] [DPID ...]
By default a product whose pull is incomplete (a site or an ITS file failed) writes nothing, so the existing
raw files stay intact; --allow-partial writes whatever succeeded.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import neon

# DP1.10081.002 = current ITS taxonomy pipeline (~2016+, incl. KONA 2019/2024, STER 2022);
# DP1.10081.001 = old pipeline (2014-2018). Both are kept; neon.load_its_raw() prefers .002 per DNA sample.
PRODUCTS = ["DP1.10081.002", "DP1.10081.001", "DP1.10109.001", "DP1.10086.001"]


def _fail(what: str, e: Exception) -> None:
    # IncompleteFetch messages are ours and token-free; for anything else print only the type
    msg = f": {e}" if isinstance(e, neon.IncompleteFetch) else ""
    print(f"  {what}FAILED {type(e).__name__}{msg}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    partial = "--allow-partial" in args
    prods = [a for a in args if a != "--allow-partial"] or PRODUCTS
    for dpid in prods:
        print(f"== {dpid}", flush=True)
        try:
            tabs = neon.fetch_product(dpid, allow_partial=partial)
        except Exception as e:  # noqa: BLE001
            _fail("", e)
            continue
        for n, df in tabs.items():
            print(f"  {n}: {len(df)} rows", flush=True)
        if dpid in neon.ITS_PRODUCTS:
            try:
                t = neon.fetch_its_sample_files(dpid, allow_partial=partial)
                print(f"  {neon.its_taxonomy_path(dpid).name} (assembled): {len(t)} rows", flush=True)
            except Exception as e:  # noqa: BLE001
                _fail("ITS sample files ", e)

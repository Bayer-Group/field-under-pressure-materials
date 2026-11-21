"""Pull NEON portal products for STER/KONA, save raw parquet, print table names + row counts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import neon

# DP1.10081.002 = current ITS taxonomy pipeline (~2016+, incl. KONA 2019/2024, STER 2022);
# DP1.10081.001 = old pipeline (2014-2018). Both are kept; neon.load_its_raw() prefers .002 per DNA sample.
PRODUCTS = ["DP1.10081.002", "DP1.10081.001", "DP1.10109.001", "DP1.10086.001"]
if __name__ == "__main__":
    prods = sys.argv[1:] or PRODUCTS
    for dpid in prods:
        print(f"== {dpid}", flush=True)
        try:
            tabs = neon.fetch_product(dpid)
        except Exception as e:  # noqa: BLE001
            print("  FAILED", type(e).__name__)
            continue
        for n, df in tabs.items():
            print(f"  {n}: {len(df)} rows", flush=True)
        if dpid in neon.ITS_PRODUCTS:
            try:
                t = neon.fetch_its_sample_files(dpid)
                print(f"  {neon.its_taxonomy_path(dpid).name} (assembled): {len(t)} rows", flush=True)
            except Exception as e:  # noqa: BLE001
                print("  ITS sample files FAILED", type(e).__name__)

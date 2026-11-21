"""Pull NEON portal products for STER/KONA, save raw parquet, print table names + row counts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import neon

PRODUCTS = ["DP1.10081.001", "DP1.10109.001", "DP1.10086.001"]
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
        if dpid == "DP1.10081.001":
            try:
                t = neon.fetch_its_sample_files()
                print(f"  mcc_soilPerSampleTaxonomy_ITS (assembled): {len(t)} rows", flush=True)
            except Exception as e:  # noqa: BLE001
                print("  ITS sample files FAILED", type(e).__name__)

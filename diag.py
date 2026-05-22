import sys
sys.stdout.reconfigure(encoding="utf-8")
import polars as pl
from pathlib import Path

# >>> EDIT THIS LINE <<<
masked_path = Path(r"K:\Sentinel\data_characterization\qa\sdd\parquet\2026-05-22\masked\dem_l3_catvars.parquet")

stacked_path = masked_path.parent.parent / "stacked" / masked_path.name

m = pl.read_parquet(str(masked_path))
s = pl.read_parquet(str(stacked_path))

print("== MASKED:", masked_path)
print("  cols:", [repr(c) for c in m.columns])
print("  rows:", len(m))

print("== STACKED:", stacked_path)
print("  cols:", [repr(c) for c in s.columns])
print("  rows:", len(s))

print("== only_in_masked :", set(m.columns) - set(s.columns))
print("== only_in_stacked:", set(s.columns) - set(m.columns))

dmap_path = masked_path.parent.parent / "dpid_map.csv"
print("== dpid_map exists:", dmap_path.exists())
if dmap_path.exists():
    d = pl.read_csv(str(dmap_path))
    print("  rows:", len(d), "cols:", d.columns)
    print(d)

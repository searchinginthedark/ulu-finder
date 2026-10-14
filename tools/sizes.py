"""Raw and gzip size of every published data file (phones download the gzip size)."""
import gzip
import os

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "data")
for f in sorted(os.listdir(D)):
    b = open(os.path.join(D, f), "rb").read()
    print(f"{f:12} {len(b) // 1024:6} KB raw {len(gzip.compress(b)) // 1024:6} KB gzip")

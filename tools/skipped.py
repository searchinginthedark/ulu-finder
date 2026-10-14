"""List articles the place-status allowlist drops, per country (needs a warm --cache).

    python tools/skipped.py SG MY
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ulu import build, wikitext  # noqa: E402

tree = build.geocrumb_tree()
countries, _ = build.load_config()
for c in countries:
    if c["cc"] not in sys.argv[1:]:
        continue
    root, _ = build.page_id(c["wv"])
    desc = build.descendants(tree, root)
    pages = build.fetch_pages(sorted(desc), os.path.join(build.ROOT, ".cache"))
    for pid in desc:
        st = wikitext.status_template(pages[pid]["text"])
        if build.not_place(st):
            print(c["cc"], st, pages[pid]["title"], len(wikitext.listings(pages[pid]["text"])))

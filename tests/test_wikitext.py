import unittest

from ulu import wikitext
from ulu.build import commons_url, dedupe, descendants, display_name, num

ARTICLE = """{{pagebanner|X.jpg}}
'''Town''' is a [[Penang|Penangite]] town with {{km|5}} of beach.

==See==
* {{see
| name=Kek Lok Si | alt={{lang|zh|极乐寺}} | lat=5.3998 | long=100.2738
| content=Huge temple; see [[Air Itam|the hill]] and [http://x.example the site]. Entry {{RM|2}}.
| wikidata=Q1050419
}}
==Eat==
===Budget===
* {{eat | name=Line Clear | address=Jalan Penang | content=Nasi kandar, '''24 hours'''.<ref>x</ref> }}
* {{listing | type=drink | name=Kopi Bar | content=}}
==Sleep==
* {{sleep | name=Hotel X }}
"""


class WikitextTest(unittest.TestCase):
    def test_listings_with_nested_templates_and_links(self):
        ls = wikitext.listings(ARTICLE)
        self.assertEqual([l["template"] for l in ls], ["see", "eat", "drink", "sleep"])
        self.assertEqual([l["section"] for l in ls], ["See", "Eat", "Eat", "Sleep"])
        see = ls[0]["params"]
        self.assertEqual(see["lat"], "5.3998")
        self.assertEqual(see["wikidata"], "Q1050419")
        self.assertEqual(wikitext.clean(see["alt"]), "极乐寺")
        self.assertEqual(wikitext.clean(see["content"]), "Huge temple; see the hill and the site. Entry 2.")

    def test_clean_strips_refs_bold_and_truncates(self):
        self.assertEqual(wikitext.clean("Nasi kandar, '''24 hours'''.<ref>x</ref>"), "Nasi kandar, 24 hours.")
        self.assertEqual(wikitext.clean("{{km|5}} of beach"), "5 km of beach")
        out = wikitext.clean("word " * 200, 40)
        self.assertTrue(out.endswith("…") and len(out) <= 41)

    def test_lede_skips_banner(self):
        self.assertTrue(wikitext.lede(ARTICLE).startswith("Town is a Penangite town with 5 km"))

    def test_status(self):
        self.assertEqual(wikitext.status_template("{{usablepark}}\ntext"), "usablepark")
        self.assertEqual(wikitext.status_template("no status"), "")

    def test_unbalanced_template_does_not_hang(self):
        self.assertEqual(wikitext.listings("{{see | name=broken"), [])


class BuildHelpersTest(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(display_name("West Coast (Malaysia)"), "West Coast")
        self.assertEqual(display_name("Singapore/Chinatown"), "Chinatown")
        self.assertEqual(display_name("Ho Chi Minh City/District 1"), "District 1")

    def test_num_rejects_garbage_and_zero(self):
        self.assertEqual(num("5.4"), 5.4)
        self.assertIsNone(num(""))
        self.assertIsNone(num("0"))
        self.assertIsNone(num("abc"))

    def test_commons_url(self):
        self.assertEqual(commons_url("File:Kek Lok Si.jpg"),
                         "https://commons.wikimedia.org/wiki/Special:FilePath/Kek_Lok_Si.jpg?width=640")
        self.assertIsNone(commons_url(""))
        self.assertIsNone(commons_url("{{{image}}}"))

    def test_descendants_paths_and_loop_safety(self):
        tree = {"2": ("West", "1"), "3": ("Penang", "2"), "4": ("George Town", "3"),
                "9": ("Loop A", "8"), "8": ("Loop B", "9"), "5": ("Elsewhere", "99")}
        d = descendants(tree, "1")
        self.assertEqual(d, {"2": ["2"], "3": ["2", "3"], "4": ["2", "3", "4"]})

    def test_dedupe_by_name_and_coords(self):
        a = {"name": "Kek Lok Si", "lat": 5.39981, "lon": 100.27382, "r1": "1", "dest": "George Town"}
        b = dict(a, lat=5.39984, dest="Air Itam")
        c = {"name": "Kek Lok Si", "lat": None, "lon": None, "r1": "1", "dest": "George Town"}
        self.assertEqual(len(dedupe([a, b, c])), 2)

    def test_dedupe_by_wikidata_across_names(self):
        a = {"name": "Mount Apo", "wd": "Q217013", "lat": 7.0, "lon": 125.2, "r1": "1", "dest": "Davao"}
        b = {"name": "Mt. Apo", "wd": "Q217013", "lat": None, "lon": None, "r1": "1", "dest": "Kidapawan"}
        c = {"name": "Mount Apo", "wd": "", "lat": None, "lon": None, "r1": "1", "dest": "Davao"}
        self.assertEqual([s["name"] for s in dedupe([a, b, c])], ["Mount Apo", "Mount Apo"])

    def test_merge_same_name(self):
        from ulu.build import merge_same_name

        def spot(name, dest="Vigan", desc="", lat=None, lon=None, cat="dine", **kw):
            return dict({"name": name, "dest": dest, "cat": cat, "desc": desc, "lat": lat, "lon": lon, "img": None, "wd": "",
                         "alt": "", "hours": "", "price": "", "addr": ""}, **kw)
        # same place listed twice: the described one wins, keeps the first slot, borrows coords and hours
        a = spot("Cafe Leona", hours="9-21", lat=17.5747, lon=120.3869)
        b = spot("Other", desc="x")
        c = spot("cafe leona", desc="Ilocano dishes by the plaza.")
        out = merge_same_name([a, b, c])
        self.assertEqual([s["name"] for s in out], ["cafe leona", "Other"])
        self.assertEqual((out[0]["lat"], out[0]["hours"]), (17.5747, "9-21"))
        # branches 1.1 km apart both stay; a coord-less listing folds into one of them
        d = spot("Jollibee", desc="Plaza branch.", lat=17.5747, lon=120.3869)
        e = spot("Jollibee", desc="Highway branch.", lat=17.5847, lon=120.3869)
        f = spot("Jollibee")
        self.assertEqual(len(merge_same_name([d, e, f])), 2)
        # near-miss: 250 m apart is one place
        g = spot("Jollibee", desc="a", lat=17.5747, lon=120.3869)
        h = spot("Jollibee", desc="b", lat=17.5769, lon=120.3869)
        self.assertEqual(len(merge_same_name([g, h])), 1)
        # near-miss: the hotel as a sight and its restaurant are two cards
        self.assertEqual(len(merge_same_name([spot("Strand Hotel", cat="sights"), spot("Strand Hotel")])), 2)
        # near-miss: same name, other destination
        self.assertEqual(len(merge_same_name([spot("Jollibee"), spot("Jollibee", dest="Laoag")])), 2)

    def test_not_place_status(self):
        from ulu.build import not_place
        for st in ("usabletopic", "outlineitinerary", "usablediveguide", "usableevent"):
            self.assertTrue(not_place(st), st)
        for st in ("guidecity", "outlineregion", "usablepark", "stardistrict", "usablecountry", "guideairport", ""):
            self.assertFalse(not_place(st), st)


class WikidataCoordTest(unittest.TestCase):
    """P625 fills coordinates only where the listing has none, and only near its destination."""

    def spot(self, lat=None, lon=None, wd="Q1", dest_ll=(13.75, 100.49)):
        return {"name": "Wat Pho", "wd": wd, "lat": lat, "lon": lon, "img": None, "alt": "", "dest_ll": dest_ll}

    def test_parse_point(self):
        from ulu.build import parse_point
        self.assertEqual(parse_point("Point(100.4930 13.7465)"), (13.7465, 100.493))
        self.assertEqual(parse_point("Point(-1.5e-3 51.5)"), (51.5, -0.0015))
        # near-misses: another globe (the Moon), null island, garbage
        self.assertIsNone(parse_point("<http://www.wikidata.org/entity/Q405> Point(23.47 0.67)"))
        self.assertIsNone(parse_point("Point(0 0)"))
        self.assertIsNone(parse_point(None))

    def test_fills_missing_coords(self):
        from ulu.build import enrich
        s = self.spot()
        enrich([s], {"Q1": {"links": 40, "coord": (13.7465, 100.493)}})
        self.assertEqual((s["lat"], s["lon"]), (13.7465, 100.493))

    def test_listing_coords_win(self):
        # near-miss: the listing has its own coords; Wikidata never overrides an editor's pin
        from ulu.build import enrich
        s = self.spot(13.70, 100.50)
        enrich([s], {"Q1": {"links": 40, "coord": (13.7465, 100.493)}})
        self.assertEqual((s["lat"], s["lon"]), (13.70, 100.50))

    def test_half_a_coordinate_is_none(self):
        from ulu.build import enrich
        s = self.spot(13.70, None)
        enrich([s], {"Q1": {"links": 40, "coord": (13.7465, 100.493)}})
        self.assertEqual((s["lat"], s["lon"]), (13.7465, 100.493))

    def test_far_item_is_a_namesake(self):
        from ulu.build import enrich
        far = self.spot()
        enrich([far], {"Q1": {"links": 3, "coord": (18.79, 98.98)}})   # Chiang Mai, ~590 km from Bangkok
        self.assertIsNone(far["lat"])
        near = self.spot()
        enrich([near], {"Q1": {"links": 3, "coord": (14.10, 100.49)}})  # near-miss: ~39 km, inside 50
        self.assertEqual(near["lat"], 14.10)

    def test_destination_without_coords_accepts(self):
        from ulu.build import enrich
        s = self.spot(dest_ll=None)
        enrich([s], {"Q1": {"links": 3, "coord": (18.79, 98.98)}})
        self.assertEqual(s["lat"], 18.79)


if __name__ == "__main__":
    unittest.main()

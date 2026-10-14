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

    def test_not_place_status(self):
        from ulu.build import not_place
        for st in ("usabletopic", "outlineitinerary", "usablediveguide", "usableevent"):
            self.assertTrue(not_place(st), st)
        for st in ("guidecity", "outlineregion", "usablepark", "stardistrict", "usablecountry", "guideairport", ""):
            self.assertFalse(not_place(st), st)


if __name__ == "__main__":
    unittest.main()

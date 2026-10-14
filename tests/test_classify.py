import unittest

from ulu.classify import classify

# (template, section, name, description, expected). Each misfire found in real output stays here
# with a near-miss beside it, so a fix for one cannot quietly break the other.
CASES = [
    ("eat", "Eat", "EE Beng Vegetarian Food", "Self-serve buffet.", "dine"),
    ("eat", "Eat", "Gurney Drive Hawker Centre", "", "markets"),
    ("eat", "Eat", "Pasar Malam Jalan Kuching", "", "markets"),
    ("eat", "Eat", "Chợ Bến Thành", "", "markets"),
    ("drink", "Drink", "Bricks and Barrels", "A gastrobar.", "cafes"),
    ("drink", "Drink", "88 Seafood Restaurant", "Family-run.", "dine"),          # misfire 2026-10-14
    ("buy", "Buy", "Queensbay Mall", "", "shopping"),
    ("buy", "Buy", "Jonker Walk Night Market", "", "markets"),
    ("buy", "Buy", "Central Market Mall", "", "shopping"),
    ("see", "See", "Kek Lok Si Temple", "", "culture"),
    ("see", "See", "Wat Tham Suea (Tiger Cave Temple)", "", "culture"),
    ("see", "See", "Mount Kinabalu", "", "nature"),
    ("see", "See", "Kipungit Waterfall", "", "nature"),
    ("see", "See", "Merdeka Park", "", "nature"),
    ("see", "See", "Sunway Lagoon Theme Park", "", "sights"),
    ("do", "Do", "Watch an event at Bukit Jalil National Stadium", "", "activities"),  # misfire 2026-10-14
    ("see", "See", "Mount Austin Sport City", "Track and field stadium.", "sights"),    # misfire 2026-10-14
    ("see", "See", "Kuala Lumpur Tower", "Tower on Bukit Nanas forest reserve hill.", "sights"),  # misfire 2026-10-14
    ("see", "See", "Bukit Nanas Forest Eco Park", "", "nature"),                       # near-miss of the above
    ("see", "See", "Chocolate Hills Complex", "", "nature"),                           # misfire 2026-10-14
    ("do", "Do", "Abellana Cebu Sports Center & Public Swimming pool", "", "activities"),  # near-miss
    ("do", "Do", "Sipadan Scuba", "PADI dive centre near the reef.", "activities"),
    ("see", "See", "Petronas Twin Towers", "Once the world's tallest buildings.", "sights"),
    ("see", "See", "Little India", "Shops and temples line the street.", "culture"),
    ("sleep", "Sleep", "Hotel Penaga", "", None),
    ("listing", "Sleep", "Some Hostel", "", None),
    ("listing", "Eat", "Line Clear Nasi Kandar", "", "dine"),
    ("listing", "Get around", "Grab", "", None),
]


class ClassifyTest(unittest.TestCase):
    def test_cases(self):
        for tmpl, sec, name, desc, want in CASES:
            with self.subTest(name=name):
                got = classify({"template": tmpl, "section": sec, "params": {}}, name, desc)
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()

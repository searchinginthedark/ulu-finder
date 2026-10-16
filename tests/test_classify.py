import unittest

from ulu.classify import classify, excluded

# (template, section, name, description, expected). Each misfire found in real output stays here
# with a near-miss beside it, so a fix for one cannot quietly break the other.
CASES = [
    ("eat", "Eat", "EE Beng Vegetarian Food", "Self-serve buffet.", "dine"),
    ("eat", "Eat", "Gurney Drive Hawker Centre", "", "markets"),
    ("eat", "Eat", "Pasar Malam Jalan Kuching", "", "markets"),
    ("eat", "Eat", "Chợ Bến Thành", "", "markets"),
    # Cafes & Desserts, not nightlife (user ruling 2026-10-15; JB's "cafes" were pubs and clubs)
    ("drink", "Drink", "Bricks and Barrels", "A gastrobar.", None),
    ("drink", "Drink", "Mulligans Irish Pub", "Irish pub.", None),                     # misfire 2026-10-15
    ("drink", "Drink", "Freedom Ultimate Club", "Night club.", None),                   # misfire 2026-10-15
    ("drink", "Drink", "Project X", "Beer bar.", None),
    ("drink", "Drink", "Nam Kwang Open Air Coffee shop", "Famous for its drinks.", "cafes"),  # near-miss
    ("drink", "Drink", "Jing-Si Books and Cafe", "Bookshop and cafe.", "cafes"),
    ("drink", "Drink", "Chatto Tangkak", "Handcrafted tea bar.", "cafes"),            # tea bar is not a bar
    ("drink", "Drink", "Tipsy Monkey", "Coffee by day, cocktails at night.", None),    # desc says bar too
    ("drink", "Drink", "Keep That Coffee (키프댓)", "", "cafes"),
    ("drink", "Drink", "Komeda", "A chain of 喫茶 coffee shops.", "cafes"),
    ("eat", "Eat", "Salahuddin Bakery", "Indian sweets and breads.", "cafes"),         # misfire 2026-10-15: was dine
    ("eat", "Eat", "Baan Kao Nhom - Traditional Thai Sweet Dessert Cafe", "", "cafes"),  # misfire 2026-10-15
    ("eat", "Eat", "Sofra Turkish Café & Restaurant", "", "dine"),                     # near-miss: restaurant wins
    ("eat", "Eat", "Dann's Cafe", "A popular place for good Johor laksa, Hyderabad biryani rice.", "dine"),  # misfire 2026-10-15
    ("eat", "Eat", "Nobita Japanese Cafe", "Japanese restaurant.", "dine"),           # misfire 2026-10-15
    ("drink", "Drink", "Greenland Tea House", "Hawker center.", "dine"),              # misfire 2026-10-15
    ("eat", "Eat", "Cafe De Kokok", "Serves coffee, pastas, pizza and pastries.", "cafes"),  # near-miss: coffee named
    ("eat", "Eat", "Kampung Cafe", "", "cafes"),                                      # near-miss: no description
    ("drink", "Drink", "Yellow Cafe", "Beach bar.", None),                            # misfire 2026-10-15
    ("drink", "Drink", "Es Teler Durian Mbak Bella", "", "cafes"),                    # misfire: Indonesian dessert drink
    ("eat", "Eat", "Halo-Halo de Iloko", "", "cafes"),
    ("eat", "Eat", "Azah Pon Cafe", "They serve the best Mee Jawa in town.", "dine"),  # misfire 2026-10-15
    ("eat", "Eat", "Ina Cafe", "A small cafe that does lunch across from the beach.", "dine"),  # "cafe" in desc is weak
    ("eat", "Eat", "Lord's cafe", "Popular place for local tea (RM2) and scones.", "cafes"),  # near-miss: tea, scones
    ("drink", "Drink", "Exodus Lounge (Formerly Known As Krabau Rock Cafe)", "Live music venue.", None),  # misfire
    ("drink", "Drink", "Kopi Corner (formerly Bar 99)", "Coffee and kaya toast.", "cafes"),  # near-miss: old name a bar
    ("drink", "Drink", "Baby Blue Cafe and Bar", "Coffee and cocktails.", "cafes"),   # near-miss: coffee in desc
    ("drink", "Drink", "Jing-Si Tea House", "A quiet tea room.", "cafes"),
    # kopitiams are Cafes (user ruling 2026-10-15), the food-court kind is Markets
    ("eat", "Eat", "Killiney Kopitiam", "Kaya toast and coffee.", "cafes"),
    ("eat", "Eat", "Ya Kun Kaya Toast", "Singapore's classic breakfast.", "cafes"),
    ("eat", "Eat", "Kedai Kopi Sin Yoon Loong", "", "cafes"),
    ("eat", "Eat", "Kopitiam", "A chain of 24-hour food courts.", "markets"),         # near-miss: SG food-court chain
    ("eat", "Eat", "Hock Kee Kopitiam", "Famous for its curry mee and char siew rice.", "dine"),  # meals, no kopi
    ("eat", "Eat", "Oyster cakes", "Fried savoury snack.", "dine"),                    # near-miss: savoury cake
    ("eat", "Eat", "Bánh Mì Bà Lan", "Sandwiches.", "dine"),                           # near-miss: bánh is not a cafe
    ("eat", "Eat", "Rock Bottom Bar", "Sports bar with a menu.", "dine"),              # Eat section keeps its pub-restaurants
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
    ("do", "Do", "Mobility Resort Motegi", "Here you will get to see the museum of Honda, Asimo apart from the race track.",
     "activities"),                                                                    # misfire 2026-10-14
    ("see", "See", "Honda Collection Hall Museum", "Inside the Motegi resort.", "culture"),  # near-miss: museum in NAME
    ("see", "See", "Dejima", "A rebuilt Dutch trading post and museum.", "culture"),     # near-miss: no venue word
    ("see", "See", "Imperial City of Hue", "The citadel and palace of the Nguyen emperors.", "culture"),  # near-miss: "city"
    ("see", "See", "Old Tutuban Train Station", "A historic Spanish-era station.", "culture"),  # near-miss: "station"
    ("sleep", "Sleep", "Hotel Penaga", "", None),
    ("listing", "Sleep", "Some Hostel", "", None),
    ("listing", "Eat", "Line Clear Nasi Kandar", "", "dine"),
    ("listing", "Get around", "Grab", "", None),
]


# (cat, name, description, destination, expected reason). Closure only when the listing says it
# about itself: a neighbour that "closed down" or is "now-defunct" never removes this one.
EXCLUDED = [
    ("culture", "Dusit Palace", "PERMANENTLY CLOSED! Sometimes called New Royal City.", "Bangkok/Dusit", "closed"),
    ("nature", "Phuket Zoo", "Elephant shows every day. Caution, Phuket Zoo may be closed permanently.", "Phuket", "closed"),
    ("cafes", "The Cuesport Cafe", "--Possibly closed down. No information online about this place--", "Ipoh", "closed"),
    ("activities", "The Jungle Water Adventure", "Unfortunately, this place has been closed since COVID-19.", "Bogor", "closed"),
    ("dine", "Old Diner (closed)", "", "Hanoi", "closed"),
    ("dine", "La Monita Taqueria", "One of the best Mexican restaurants, especially since Tacos and Salsa closed down.",
     "Bangkok/Sukhumvit", None),                                                       # near-miss: a neighbour closed
    ("cafes", "Living Room", "At the site of the now-defunct Monkey Club. A quiet place.", "Chiang Mai", None),  # near-miss
    ("dine", "Som Tam Nua", "Closed on Mondays. Papaya salad.", "Bangkok/Siam", None),  # hours, not closure
    ("dine", "Bourbon St", "It is closed on Sundays.", "Bangkok/Sukhumvit", None),     # hours, not closure
    ("dine", "Noodle Corner", "Closed 14:00-17:00 every day.", "Ipoh", None),          # hours, not closure
    ("dine", "Old Noodle Corner", "Closed. The owner retired in 2021.", "Ipoh", "closed"),
    ("dine", "Riverside Grill", "Closed in 2020, the site is now a car park.", "Ipoh", "closed"),
    ("culture", "Brunei Museum", "Has unfortunately been closed since 2014 undergoing renovations.", "Bandar Seri Begawan",
     "closed"),
    ("dine", "Hinomaru", "Permanently Closed as of December 2024.", "Batangas City", "closed"),
    ("nature", "Yama-Jigoku (permanently closed)", "", "Beppu", "closed"),
    # misfires 2026-10-15, all from the first all-pages sample: history, hours, neighbours
    ("culture", "Dulan Hsintung Sugar Factory", "The culture park used to be a sugar refinery, which closed in 1991.",
     "Donghe", None),
    ("cafes", "Forbidden City Cafe", "After the Starbucks branch closed in 2007, the former Duty Room became a cafe.",
     "Beijing", None),
    ("sights", "Jiuquan Satellite Launch Center", "Closed to foreigners.", "Jiuquan", None),
    ("shopping", "Kiryu Orimono Kinenkan", "Closed the last Saturday and Sunday of the month.", "Kiryu", None),
    ("culture", "Chongqing Mahjong Museum", "The successor to a museum in Chiba, which closed down in 2012.",
     "Chongqing", None),
    ("markets", "Tsukiji Outer Market", "Although the wholesale operations closed in 2018, the outer market thrives.",
     "Tokyo/Chuo", None),
    ("dine", "Es Teler Durian Mbak Bella", "Durian iced dessert.", "Ngawi", None),
    ("nature", "Trail 11", "This trail was closed due to landslides in 2017, but it is open and walkable.",
     "Cameron Highlands", None),
    ("culture", "Cultural & Sports Complex", "There is a museum across the river, but it is closed.", "Zhongwei", None),
    ("nature", "Sokcho Beach", "You can still get on to the beach even when it is closed.", "Sokcho", None),
    ("dine", "McDonalds", "24 hours.", "Kuala Lumpur International Airport", "chain"),
    ("cafes", "Starbucks Reserve", "", "Tokyo/Shibuya", "chain"),
    ("dine", "Hard Rock Cafe", "", "Kota Kinabalu", "chain"),
    ("dine", "Jollibee", "Filipino fried chicken.", "Metro Manila", None),             # near-miss: home-grown chain stays
    ("cafes", "Old Town White Coffee", "White coffee and toast.", "Ipoh", None),                              # near-miss: home-grown chain stays
    ("dine", "Subway Noodle House", "", "Taipei", "chain"),                            # accepted false positive, rare
    ("dine", "Nasi Lemak Stall", "", "Kuala Lumpur International Airport", "airport"),
    ("sights", "Jewel Changi", "Indoor waterfall.", "Changi Airport", None),           # near-miss: not food
    ("dine", "Jumbo Seafood Jewel", "Chilli crab.", "Changi Airport", None),           # Changi food stays (user ruling)
    ("dine", "Nasi Lemak Kukus", "", "Ninoy Aquino International Airport", "airport"),
    ("dine", "Airport Road Hawker", "Char kway teow.", "Penang", None),                               # near-miss: "airport" in the name only
    ("shopping", "Starbucks merchandise", "", "Seoul", None),                          # near-miss: chains only drop in food
    ("cafes", "Gloria Jean's Coffee", "", "Kuala Lumpur", "chain"),
    ("cafes", "Various cafes in Bandar Sunway", "Old Town Kopitiam, Swenz, Sri Wan.", "Subang Jaya", "generic"),
    ("sights", "Various Temples Street", "", "Ipoh", "generic"),                       # accepted: no real place starts so
    ("dine", "Manyfold Bistro", "Western food.", "Ipoh", None),                                     # near-miss: word boundary
    ("cafes", "Many Coffee", "Lao coffee.", "Sam Neua", None),                                    # misfire 2026-10-15: a real cafe
    ("culture", "Other Great Wall ruins", "", "Qinhuangdao", "generic"),
    # no description (user ruling 2026-10-16): food only, and a stronger reason wins
    ("dine", "Kainan sa Plaza", "", "Vigan", "nodesc"),
    ("cafes", "Kopi Corner", "   ", "Ipoh", "nodesc"),
    ("markets", "Pasar Pagi", "", "Ipoh", "nodesc"),
    ("sights", "Clock Tower", "", "Ipoh", None),                                      # near-miss: not food
    ("dine", "Old Diner (closed)", "", "Hanoi", "closed"),                             # closed outranks nodesc
]

# (cat, name, description, destination, country, expected). Regional chains stay only at home
# (user ruling 2026-10-16).
REGIONAL = [
    ("dine", "Jollibee", "Fried chicken.", "Metro Manila", "PH", None),
    ("dine", "Jollibee", "Fried chicken.", "Bandar Seri Begawan", "BN", "chain"),
    ("dine", "Mang Inasal Baler Branch", "Grilled chicken.", "Baler", "PH", None),
    ("dine", "Din Tai Fung", "Xiaolongbao.", "Taipei", "TW", None),
    ("dine", "Din Tai Fung", "Xiaolongbao.", "Singapore/Orchard", "SG", "chain"),
    ("cafes", "Gong Cha (贡茶 巴中店)", "Bubble tea.", "Bazhong", "CN", "chain"),
    ("cafes", "Café Amazon-San Fernando Pampanga", "Thai coffee chain.", "San Fernando", "PH", "chain"),
    ("cafes", "Cafe Amazon", "Coffee.", "Chiang Mai", "TH", None),
    ("cafes", "Highlands Coffee (North Location)", "Coffee.", "Kunming", "CN", "chain"),
    ("dine", "Pho 24", "Noodle soup.", "Jakarta", "ID", "chain"),
    ("dine", "Lotteria", "Burgers.", "Seoul", "KR", None),                            # two homes
    ("dine", "Lotteria", "Burgers.", "Tokyo/Shibuya", "JP", None),
    ("dine", "Lotteria", "Burgers.", "Hanoi", "VN", "chain"),
    ("dine", "Sukiya", "Gyudon.", "Tokyo/Shinjuku", "JP", None),
    ("dine", "Sukiyabashi Jiro", "Sushi.", "Tokyo/Chuo", "JP", None),                  # near-miss: not Sukiya
    ("dine", "Sukiyaki Ichiban", "Sukiyaki.", "Taipei", "TW", None),                   # near-miss: not Sukiya
    ("shopping", "Mitsukoshi and Matsuya Ginza's", "Department stores.", "Tokyo/Chuo", "JP", None),
    ("dine", "Coco Ichibanya", "Curry.", "Shanghai", "CN", "chain"),
    ("dine", "COCO", "Bar food.", "Dali", "CN", None),                                  # near-miss: bare word
    ("cafes", "Bo's Coffee Dagupan", "Coffee.", "Dagupan", "PH", None),
    ("cafes", "Bo's Cafe", "Coffee and cake.", "Pai", "TH", None),                     # misfire 2026-10-16: not Bo's Coffee
    ("dine", "Maxim's Palace", "Dim sum.", "Hong Kong/Central", "HK", None),            # near-miss: not Max's
    ("shopping", "Jollibee merchandise", "", "Brunei", "BN", None),                     # chains drop in food only
    ("dine", "Jollibee", "Fried chicken.", "Bandar Seri Begawan", None, None),          # no country: rule off
]


class ClassifyTest(unittest.TestCase):
    def test_cases(self):
        for tmpl, sec, name, desc, want in CASES:
            with self.subTest(name=name):
                got = classify({"template": tmpl, "section": sec, "params": {}}, name, desc)
                self.assertEqual(got, want)

    def test_excluded(self):
        for cat, name, desc, dest, want in EXCLUDED:
            with self.subTest(name=name):
                self.assertEqual(excluded(cat, name, desc, dest), want)

    def test_regional_chains(self):
        for cat, name, desc, dest, cc, want in REGIONAL:
            with self.subTest(name=name, cc=cc):
                self.assertEqual(excluded(cat, name, desc, dest, cc), want)


class EditYearTest(unittest.TestCase):
    def test_formats(self):
        from ulu.build import edit_year
        for v, want in [("2019-05-12", 2019), ("2019-5-1", 2019), ("2021-03", 2021), ("2018", 2018),
                        ("", None), (None, None), ("permanent", None), ("Sep 2019", None), ("20190512", None)]:
            with self.subTest(v=v):
                self.assertEqual(edit_year(v), want)


if __name__ == "__main__":
    unittest.main()

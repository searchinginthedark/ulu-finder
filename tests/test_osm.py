import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from ulu import osm
from ulu.build import carry_lookups, previous_lookups

TH_LAT, TH_LON = 18.7883, 98.9853   # Chiang Mai old city


def offset(metres_north):
    return TH_LAT + metres_north / 111_320.0


def spot(name, cat="dine", lat=TH_LAT, lon=TH_LON, local="", src="https://en.wikivoyage.org/wiki/Chiang_Mai#Eat"):
    return {"id": "x", "name": name, "local": local, "cat": cat, "lat": lat, "lon": lon,
            "desc": "d", "hours": "", "price": "", "addr": "", "img": None, "score": 0,
            "src": src, "signals": {}, "listed_by": "wikivoyage"}


def poi(names, north=0.0, **tags):
    tags = dict(tags)
    tags.setdefault("name", names[0])
    return {"lat": offset(north), "lon": TH_LON, "names": {osm.norm(n) for n in names}, "tags": tags}


class NormTest(unittest.TestCase):
    def test_latin_accents_dropped(self):
        self.assertEqual(osm.norm("Sky Café"), "sky cafe")
        self.assertEqual(osm.norm("Phở Hòa"), "pho hoa")

    def test_thai_vowel_signs_kept(self):
        # near-miss: Thai vowels are combining marks too; dropping them merges different names
        self.assertEqual(osm.norm("ทองพูน"), "ทองพูน")
        self.assertNotEqual(osm.norm("ทองพูน"), osm.norm("ทองพน"))


class MatchTest(unittest.TestCase):
    """Fixtures are real TH pairs from the 2026-10-14 measurement, each with a near-miss."""

    def matched(self, s, pois):
        return osm.match([s], pois).get(osm.spot_key(s))

    def test_exact_name_nearby(self):
        self.assertIsNotNone(self.matched(spot("Peppers Restaurant & Bakery"), [poi(["Peppers Restaurant & Bakery"], 12)]))

    def test_exact_name_too_far_is_no_match(self):
        # near-miss: same name, 160 m away (RADIUS is 150)
        self.assertIsNone(self.matched(spot("Peppers Restaurant & Bakery"), [poi(["Peppers Restaurant & Bakery"], 160)]))

    def test_short_name_inside_listing_name(self):
        self.assertIsNotNone(self.matched(spot("Norden Restaurant Chiang Mai"), [poi(["Norden"], 16)]))

    def test_containment_needs_five_characters(self):
        # near-miss: "Sky" is too short to count as a whole-word part of "Sky Cafe Garden"
        self.assertIsNone(self.matched(spot("Sky Cafe Garden"), [poi(["Sky"], 5)]))

    def test_different_bars_do_not_match(self):
        # measured near-miss: "Friendly Bar" sat 30 m from "Kalae Bar" (en "Orion Bar"), sim 0.67
        self.assertIsNone(self.matched(spot("Friendly Bar", cat="cafes"), [poi(["Kalae Bar", "Orion Bar"], 30)]))

    def test_thai_name_variant_matches(self):
        # "Thong Poon" matched ทองพูน through a romanised name variant
        p = poi(["ทองพูน", "Thong Poon"], 9)
        self.assertIsNotNone(self.matched(spot("Thong Poon"), [p]))

    def test_local_label_matches_thai_name(self):
        self.assertIsNotNone(self.matched(spot("Golden Pot", local="ทองพูน"), [poi(["ทองพูน"], 9)]))

    def test_best_candidate_wins(self):
        exact_far = poi(["Anchan Vegetarian Restaurant"], 100, cuisine="thai")
        partial_near = poi(["Anchan"], 10)
        got = self.matched(spot("Anchan Vegetarian Restaurant"), [partial_near, exact_far])
        self.assertIs(got, exact_far)

    def test_non_food_spots_are_ignored(self):
        # D is a food signal: temples are mapped bare
        self.assertEqual(osm.match([spot("Wat Lok Moli", cat="culture")], [poi(["Wat Lok Moli"], 5)]), {})

    def test_spot_without_coords_is_skipped(self):
        self.assertEqual(osm.match([spot("Peppers", lat=None, lon=None)], [poi(["Peppers"], 0)]), {})


class DetailTest(unittest.TestCase):
    def test_chain_scores_zero(self):
        # Hard Rock Cafe carried 5 detail tags in the measurement: brand data, not local mapping
        tags = {"name": "Hard Rock Cafe", "brand": "Hard Rock Cafe", "opening_hours": "x", "website": "x",
                "phone": "x", "cuisine": "american", "addr:street": "x"}
        self.assertEqual(osm.detail(tags, "th"), (0, [], True))

    def test_operator_is_not_a_chain(self):
        # near-miss: temples and municipal markets carry an operator
        self.assertEqual(osm.detail({"name": "Market", "operator": "City of Chiang Mai"}, "th"), (0, [], False))

    def test_one_point_per_group(self):
        d, has, chain = osm.detail({"name": "A", "phone": "1", "contact:phone": "2", "opening_hours": "x"}, "th")
        self.assertEqual((d, has, chain), (2, ["hours", "phone"], False))

    def test_diet_prefix(self):
        self.assertEqual(osm.detail({"name": "A", "diet:halal": "yes"}, "ms")[1], ["diet"])

    def test_local_script_name(self):
        self.assertEqual(osm.detail({"name": "ทองพูน"}, "th"), (2, ["local_name", "local_primary"], False))

    def test_ascii_name_is_not_local_script(self):
        self.assertEqual(osm.detail({"name": "Nasi Kandar Line Clear"}, "ms"), (0, [], False))

    def test_explicit_local_name_tag(self):
        # a Thai translation under an English main name: local, but not primary
        self.assertEqual(osm.detail({"name": "Thong Poon", "name:th": "ทองพูน"}, "th"), (2, ["local_name"], False))


class LocalScriptTest(unittest.TestCase):
    # Misfires on TH 2026-10-15: "any non-ASCII letter" read European accents and Chinese as Thai.
    def test_european_accents_are_not_thai(self):
        self.assertEqual(osm.local_name_tags({"name": "Zum grünen Baum"}, "th"), [])
        self.assertEqual(osm.local_name_tags({"name": "Mirabelle épicerie fine"}, "th"), [])

    def test_chinese_is_not_thai(self):
        self.assertEqual(osm.local_name_tags({"name": "CaveCave 洞洞"}, "th"), [])

    def test_thai_inside_a_mixed_name_counts(self):
        # near-miss: Thai script anywhere in the main name is the local sign
        self.assertEqual(osm.local_name_tags({"name": "ร้าน Jay Fai"}, "th"), ["local_name", "local_primary"])

    def test_latin_text_in_name_th_is_not_thai(self):
        # Wombat & Kiwi Bar: name:th = "Wombat and Kiwi Bar"
        tags = {"name": "Wombat Bar", "name:en": "Wombat and Kiwi Bar", "name:th": "Wombat and Kiwi Bar"}
        self.assertEqual(osm.local_name_tags(tags, "th"), [])

    def test_thai_script_name_th_counts(self):
        # near-miss: Ristr8to's name:th is a Thai-script transliteration
        self.assertEqual(osm.local_name_tags({"name": "Ristr8to", "name:th": "ด็อปปิโอ ริสเทรสโต้"}, "th"), ["local_name"])

    def test_vietnamese_needs_vietnamese_letters(self):
        self.assertEqual(osm.local_name_tags({"name": "Phở Thìn"}, "vi"), ["local_name", "local_primary"])
        # near-miss: an accent Vietnamese shares with French is not enough
        self.assertEqual(osm.local_name_tags({"name": "Café de Paris"}, "vi"), [])

    def test_regional_language_code_uses_its_base_script(self):
        # TW is "zh-tw"; Chinese characters are its script, and name:zh is its tag
        self.assertEqual(osm.local_name_tags({"name": "鼎泰豐"}, "zh-tw"), ["local_name", "local_primary"])
        self.assertEqual(osm.local_name_tags({"name": "Din Tai Fung", "name:zh": "鼎泰豐"}, "zh-tw"), ["local_name"])

    def test_latin_script_language_keeps_its_name_tag(self):
        # MY: Malay is written in Latin letters, so an explicit name:ms still counts (not primary)
        self.assertEqual(osm.local_name_tags({"name": "Old Town", "name:ms": "Kedai Kopi Lama"}, "ms"), ["local_name"])
        self.assertEqual(osm.local_name_tags({"name": "Nasi Kandar Line Clear"}, "ms"), [])

    def test_japanese_kana_and_kanji(self):
        self.assertEqual(osm.local_name_tags({"name": "ザ・ロック"}, "ja"), ["local_name", "local_primary"])
        self.assertEqual(osm.local_name_tags({"name": "Sone"}, "ja"), [])


class GuardTest(unittest.TestCase):
    def test_first_week_accepts(self):
        self.assertTrue(osm.accept(300, None))

    def test_collapse_is_an_outage(self):
        self.assertFalse(osm.accept(69, 100))

    def test_at_the_floor_accepts(self):
        self.assertTrue(osm.accept(70, 100))  # near-miss: exactly 70%

    def test_small_pool_is_not_judged(self):
        self.assertTrue(osm.accept(2, 19))

    def test_zero_matches_on_a_big_country_is_an_outage(self):
        # an extract that does not cover the country (HK/MO on the China file is unverified)
        self.assertFalse(osm.accept(0, None, food_spots=50))
        self.assertTrue(osm.accept(0, None, food_spots=49))

    def test_freshness(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.assertTrue(osm.fresh(now - timedelta(days=8), now))
        self.assertFalse(osm.fresh(now - timedelta(days=8, seconds=1), now))
        self.assertFalse(osm.fresh(None, now))  # an unknown age is not a fresh one

    def test_md5_parse(self):
        self.assertEqual(osm.parse_md5("A" * 32 + "  thailand-latest.osm.pbf\n"), "a" * 32)
        with self.assertRaises(osm.OsmError):
            osm.parse_md5("<html>404</html>")


class AttachTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "data", "osm"))
        self.food = spot("Peppers Restaurant & Bakery")
        self.plain = spot("O'Malley's Irish Pub", cat="cafes")
        self.chain = spot("Hard Rock Cafe", src="https://en.wikivoyage.org/wiki/Bangkok#Eat")
        self.temple = spot("Wat Lok Moli", cat="culture")

    def write(self, as_of):
        entries = {osm.spot_key(self.food): {"d": 5, "has": ["hours", "cuisine", "local_name"]},
                   osm.spot_key(self.plain): {"d": 3, "has": ["hours", "phone", "web"]},
                   osm.spot_key(self.chain): {"d": 0, "chain": True},
                   osm.spot_key(self.temple): {"d": 3}}
        with open(os.path.join(self.root, "data", "osm", "TH.json"), "w", encoding="utf-8") as f:
            json.dump({"cc": "TH", "as_of": as_of, "matched": 3, "spots": entries}, f)

    def test_adds_only_osm_signals(self):
        self.write("2026-10-17")
        spots = [self.food, self.plain, self.chain, self.temple]
        before = copy.deepcopy(spots)
        got = osm.attach(spots, "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(got, "2026-10-17")
        self.assertEqual(self.food["signals"], {"osm_local": 1})
        # near-miss: thoroughly mapped (hours, phone, web) but no Thai name scores 0; detail is
        # not locality (TH: foreign places averaged MORE detail tags than local ones)
        self.assertEqual(self.plain["signals"], {"osm_local": 0})
        self.assertEqual(self.chain["signals"], {"osm_local": 0, "osm_chain": True})
        # licence invariant: OpenStreetMap never changes a Wikivoyage field
        for s, b in zip(spots, before):
            self.assertEqual({k: v for k, v in s.items() if k != "signals"}, {k: v for k, v in b.items() if k != "signals"})

    def test_graded_by_main_name(self):
        # format 2: a Thai main name is 1, a Thai translation under a foreign main name is 0.5
        self.write("2026-10-17")
        path = os.path.join(self.root, "data", "osm", "TH.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["format"] = osm.FORMAT
        doc["spots"][osm.spot_key(self.food)]["has"] = ["local_name", "local_primary"]
        doc["spots"][osm.spot_key(self.plain)]["has"] = ["web", "local_name"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        osm.attach([self.food, self.plain], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(self.food["signals"], {"osm_local": 1})
        self.assertEqual(self.plain["signals"], {"osm_local": 0.5})

    def test_old_format_file_reads_binary(self):
        # near-miss: a file written before local_primary existed must not halve every local name
        self.write("2026-10-17")
        osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(self.food["signals"], {"osm_local": 1})

    def test_area_matches_can_be_switched_off(self):
        # JP: the holdout trusted its area matches, but osm_check failed with them (top-30 foreign
        # 20% vs 12% base). Point matches still count; near-miss: the same entry without "via".
        self.write("2026-10-17")
        path = os.path.join(self.root, "data", "osm", "TH.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["spots"][osm.spot_key(self.plain)]["via"] = "area"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        osm.attach([self.food, self.plain], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None, use_area=False)
        self.assertEqual(self.food["signals"], {"osm_local": 1})
        self.assertEqual(self.plain["signals"], {})

    def test_culture_is_never_given_osm(self):
        self.write("2026-10-17")
        osm.attach([self.temple], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(self.temple["signals"], {})

    def test_stale_file_is_not_used(self):
        self.write("2026-09-12")  # 36 days before 2026-10-18
        self.assertIsNone(osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None))
        self.assertEqual(self.food["signals"], {})

    def test_file_at_the_age_limit_is_used(self):
        self.write("2026-09-13")  # near-miss: exactly 35 days
        self.assertEqual(osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None), "2026-09-13")

    def test_missing_file_is_no_data(self):
        self.assertIsNone(osm.attach([self.food], "VN", self.root, log=lambda m: None))
        self.assertEqual(self.food["signals"], {})

    def write_nb(self, nb, nb_area=()):
        self.write("2026-10-17")
        path = os.path.join(self.root, "data", "osm", "TH.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["nb"], doc["nb_area"] = nb, list(nb_area)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def test_neighbourhood_share_is_attached(self):
        # also on a food spot OSM never matched, and with no osm_local (it is not a match signal)
        lone = spot("Khao Soi Mae Sai")
        self.write_nb({osm.spot_key(self.food): 0.4, osm.spot_key(lone): 0.25, osm.spot_key(self.temple): 0.9})
        osm.attach([self.food, lone, self.temple], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(self.food["signals"], {"osm_local": 1, "osm_nb_local": 0.4})
        self.assertEqual(lone["signals"], {"osm_nb_local": 0.25})
        # near-miss: a culture spot never gets it, even if a file carried one
        self.assertEqual(self.temple["signals"], {})

    def test_neighbourhood_located_by_area_follows_osm_area(self):
        lost_ = spot("Khao Soi Mae Sai", lat=None, lon=None)
        self.write_nb({osm.spot_key(lost_): 0.3, osm.spot_key(self.food): 0.4}, nb_area=[osm.spot_key(lost_)])
        osm.attach([lost_, self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None, use_area=False)
        self.assertEqual(lost_["signals"], {})
        # near-miss: the geolocated spot keeps its share with area matches off
        self.assertEqual(self.food["signals"]["osm_nb_local"], 0.4)

    def test_neighbourhood_can_be_switched_off(self):
        # JP, MY (countries.json osm_nb: false): the tie-break made the top 30 more foreign there.
        # osm_local is untouched; near-miss: the same file with use_nb on attaches the share.
        self.write_nb({osm.spot_key(self.food): 0.4})
        osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None, use_nb=False)
        self.assertEqual(self.food["signals"], {"osm_local": 1})
        self.food["signals"] = {}
        osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertEqual(self.food["signals"], {"osm_local": 1, "osm_nb_local": 0.4})

    def test_file_without_neighbourhood_is_no_data(self):
        self.write("2026-10-17")
        osm.attach([self.food], "TH", self.root, today=date(2026, 10, 18), log=lambda m: None)
        self.assertNotIn("osm_nb_local", self.food["signals"])

    def test_key_survives_recategorisation(self):
        moved = dict(self.food, cat="cafes", id="other")
        self.assertEqual(osm.spot_key(moved), osm.spot_key(self.food))


class NeighbourhoodTest(unittest.TestCase):
    """Share of named food places within NB_RADIUS whose MAIN name is in the local script."""

    def street(self, thai, other, start=20):
        pois = [food_poi([f"ร้าน{i}"], start + 10 * i) for i in range(thai)]
        pois += [food_poi([f"Bar {i}"], start + 10 * (thai + i), amenity="bar") for i in range(other)]
        return pois

    def nb(self, spots, pois, found=()):
        return osm.neighbourhood(spots, pois, "th", found)

    def test_share_of_local_main_names(self):
        s = spot("Khao Soi Mae Sai")
        got, area = self.nb([s], self.street(3, 2))
        self.assertEqual(got, {osm.spot_key(s): 0.6})
        self.assertEqual(area, set())

    def test_fewer_than_five_is_no_measurement(self):
        s = spot("Khao Soi Mae Sai")
        self.assertEqual(self.nb([s], self.street(3, 1))[0], {})  # near-miss of the test above: 4 places

    def test_only_within_the_radius(self):
        s = spot("Khao Soi Mae Sai")
        pois = self.street(3, 2) + [food_poi(["ร้านไกล"], osm.NB_RADIUS + 40)]
        self.assertEqual(self.nb([s], pois)[0], {osm.spot_key(s): 0.6})

    def test_translation_is_not_a_main_name(self):
        # name:th under a Latin main name counts as foreign here, as osm_local's 0.5 says it is
        s = spot("Khao Soi Mae Sai")
        pois = self.street(2, 2) + [food_poi(["Wombat", "วอมแบท"], 70, **{"name:th": "วอมแบท"})]
        self.assertEqual(self.nb([s], pois)[0], {osm.spot_key(s): 0.4})

    def test_non_food_places_are_not_counted(self):
        s = spot("Khao Soi Mae Sai")
        pois = self.street(3, 2) + [poi(["วัดใหม่"], 70, amenity="place_of_worship")]
        self.assertEqual(self.nb([s], pois)[0], {osm.spot_key(s): 0.6})

    def test_own_match_is_left_out(self):
        s = spot("Khao Soi Mae Sai")
        pois = self.street(3, 3)
        mine = pois[0]
        got, _ = self.nb([s], pois, [(osm.spot_key(s), mine, None)])
        self.assertEqual(got, {osm.spot_key(s): 0.4})   # 2 Thai of 5 others
        self.assertEqual(self.nb([s], pois)[0], {osm.spot_key(s): 0.5})  # near-miss: unmatched, all 6

    def test_spot_without_coords_uses_its_area_match(self):
        s = spot("Khao Soi Mae Sai", lat=None, lon=None)
        pois = self.street(4, 2)
        got, area = self.nb([s], pois, [(osm.spot_key(s), pois[0], "area")])
        self.assertEqual(got, {osm.spot_key(s): 0.6})
        self.assertEqual(area, {osm.spot_key(s)})
        self.assertIsNone(s["lat"])   # licence: the place's location is never written to the spot
        self.assertEqual(self.nb([s], pois)[0], {})   # near-miss: no match, no location, no share

    def test_food_only(self):
        s = spot("Wat Lok Moli", cat="culture")
        self.assertEqual(self.nb([s], self.street(5, 0))[0], {})


class LookupFallbackTest(unittest.TestCase):
    def test_carries_only_signal_a(self):
        prev = {"generated": "2026-10-12T19:40:00Z",
                "spots": [dict(spot("Wat Phra Singh", cat="culture"),
                               signals={"local_views": 900, "local_share": 0.8, "sitelinks": 40, "osm_detail": 3})]}
        carry, as_of = previous_lookups(prev)
        self.assertEqual(as_of, "2026-10-12")
        now = dict(spot("Wat Phra Singh", cat="culture"), signals={"sitelinks": 41})
        before = copy.deepcopy(now)
        carry_lookups([now], carry)
        # this week's sitelinks stay; only A comes back; nothing else on the spot changes
        self.assertEqual(now["signals"], {"sitelinks": 41, "local_views": 900, "local_share": 0.8})
        self.assertEqual({k: v for k, v in now.items() if k != "signals"}, {k: v for k, v in before.items() if k != "signals"})

    def test_prefers_the_recorded_lookup_date(self):
        _, as_of = previous_lookups({"generated": "2026-10-12T00:00:00Z", "signals_as_of": {"lookups": "2026-10-05"}, "spots": []})
        self.assertEqual(as_of, "2026-10-05")

    def test_no_previous_file(self):
        self.assertEqual(previous_lookups(None), (None, None))


def town(dest="Chiang Mai", up=("Northern Thailand",)):
    """Three geolocated listings 0-1 km north of TH_LAT: an area of radius AREA_MIN_R (2 km)
    centred 500 m north. Sights, so they never compete for a food match themselves."""
    return [dict(spot(f"Sight {i}", cat="sights", lat=offset(500 * i)), dest=dest, up=list(up)) for i in range(3)]


def lost(name, cat="dine", dest="Chiang Mai", up=("Northern Thailand",), local=""):
    """A food listing with no coordinates in that town."""
    return dict(spot(name, cat=cat, lat=None, lon=None, local=local), dest=dest, up=list(up))


def food_poi(names, north=0.0, amenity="restaurant", **tags):
    return poi(names, north, amenity=amenity, **tags) if amenity else poi(names, north, **tags)


class AreaMatchTest(unittest.TestCase):
    """Real pairs from the 2026-10-15 TH/VN/MY holdout (geolocated food spots matched as if they
    had no coords), each with a near-miss. The area match feeds osm_local only."""

    def matched(self, s, pois, extra=()):
        return osm.area_match(town() + list(extra) + [s], pois).get(osm.spot_key(s))

    def test_name_inside_the_town(self):
        self.assertIsNotNone(self.matched(lost("Somboon Seafood"), [food_poi(["สมบูรณ์โภชนา", "Somboon Seafood"], 1500)]))

    def test_outside_the_town_is_no_match(self):
        # near-miss: same name 2.6 km from the area's centre (radius 2 km)
        self.assertIsNone(self.matched(lost("Somboon Seafood"), [food_poi(["Somboon Seafood"], 3100)]))

    def test_spot_with_coords_is_left_to_point_match(self):
        s = dict(spot("Somboon Seafood"), dest="Chiang Mai", up=["Northern Thailand"])
        self.assertEqual(osm.area_match(town() + [s], [food_poi(["Somboon Seafood"], 1500)]), {})

    def test_too_few_geolocated_listings_draw_no_area(self):
        # near-miss of test_name_inside_the_town: two listings cannot outline a town
        self.assertEqual(osm.area_match(town()[:2] + [lost("Somboon Seafood")], [food_poi(["Somboon Seafood"], 500)]), {})

    def test_type_word_alone_is_not_a_name(self):
        # measured: "Minburi Market" picked a stall mapped as "Market" 18 km away
        self.assertIsNone(self.matched(lost("Minburi Market", cat="markets"), [food_poi(["Market"], 900, amenity="marketplace")]))
        # near-miss: the distinctive word survives the type word
        self.assertIsNotNone(self.matched(lost("Thewet Market", cat="markets"), [food_poi(["Thewet market"], 900, amenity="marketplace")]))

    def test_town_name_is_not_the_place(self):
        # measured: "Ao Nang Mosque Market" matched "Ao Nang Night Market"; only "mosque" says which
        s = lost("Ao Nang Mosque Market", cat="markets", dest="Ao Nang", up=("Krabi Province",))
        t = town("Ao Nang", ("Krabi Province",))
        self.assertEqual(osm.area_match(t + [s], [food_poi(["Ao Nang Night Market"], 700, amenity="marketplace")]), {})
        # near-miss: the same market under its own words
        got = osm.area_match(t + [s], [food_poi(["Mosque Market Ao Nang"], 700, amenity="marketplace")])
        self.assertIn(osm.spot_key(s), got)

    def test_only_food_places(self):
        # measured: "Kinnaree" matched a massage parlour, "Cafe de Moei" a resort
        self.assertIsNone(self.matched(lost("Kinnaree"), [food_poi(["Kinnaree massage and massage"], 400, amenity=None, shop="massage")]))
        self.assertIsNone(self.matched(lost("Kinnaree"), [food_poi(["Kinnaree"], 400, amenity=None, tourism="hotel")]))
        # near-miss: the same name on a restaurant
        self.assertIsNotNone(self.matched(lost("Kinnaree"), [food_poi(["Kinnaree"], 400)]))

    def test_two_namesakes_are_ambiguous(self):
        # branches or a common name: two places 900 m apart, no way to tell which
        a, b = food_poi(["Uncle Don's"], 100), food_poi(["Uncle Don's"], 1000)
        self.assertIsNone(self.matched(lost("Uncle Don's"), [a, b]))

    def test_node_and_building_are_one_place(self):
        # near-miss: the same place mapped twice, 40 m apart
        a, b = food_poi(["Uncle Don's"], 100), food_poi(["Uncle Don's"], 140)
        self.assertIsNotNone(self.matched(lost("Uncle Don's"), [a, b]))

    def test_no_containment_across_a_town(self):
        # measured: "Sinthorn Steak House" -> "Steak Bar & Grill" 8.5 km away via whole-word containment
        self.assertIsNone(self.matched(lost("Sinthorn Steak House"), [food_poi(["Steak Bar & Grill"], 600)]))
        self.assertIsNone(self.matched(lost("White House Bar", cat="cafes"), [food_poi(["White Lotus Restaurant"], 600)]))
        # near-miss: the same place spelled a little differently
        self.assertIsNotNone(self.matched(lost("News Steaks & Grill"), [food_poi(["News Steaks and Grill"], 600)]))

    def test_fuzzy_must_hold_word_by_word(self):
        # measured: "Restoran Shang Ji" -> "Restoran Huang Ji" (whole-string ratio 0.88)
        self.assertIsNone(self.matched(lost("Restoran Shang Ji"), [food_poi(["Restoran Huang Ji"], 600)]))
        self.assertIsNone(self.matched(lost("Ngoc Huong", cat="cafes"), [food_poi(["Ngọc Phụng", "Ngoc Phung"], 600, amenity="cafe")]))
        # near-miss: one letter apart in every word is the same place
        self.assertIsNotNone(self.matched(lost("Cha Arnon Coffee", cat="cafes"), [food_poi(["Cha Anon Cafe"], 600, amenity="cafe")]))

    def test_one_short_word_is_not_enough(self):
        # measured: "Suria Market" -> "Suria Food" and "Inn Lucky" -> "Lucky Bar", different places
        self.assertIsNone(self.matched(lost("Suria Market", cat="markets"), [food_poi(["Suria Food"], 600)]))
        self.assertIsNone(self.matched(lost("Inn Lucky"), [food_poi(["Lucky Bar"], 600, amenity="bar")]))
        # near-miss: six letters is enough
        self.assertIsNotNone(self.matched(lost("Pisces"), [food_poi(["Pisces - Bar & Restaurant"], 600)]))

    def test_local_type_words(self):
        # Malay "Restoran", Vietnamese "Quán": the measured near-misses were the same place
        self.assertIsNotNone(self.matched(lost("Restaurant Al Fariz Maju"), [food_poi(["Restoran Al Fariz Maju"], 600)]))
        self.assertIsNotNone(self.matched(lost("Legend Beer", cat="cafes"), [food_poi(["Quán Beer Legend"], 600, amenity="biergarten")]))
        self.assertIsNotNone(self.matched(lost("Vasco's", cat="cafes"), [food_poi(["Quán Vasco's Bar and Lounge"], 600, amenity="nightclub")]))

    def test_entries_mark_area_matches_and_touch_no_field(self):
        s = lost("Somboon Seafood")
        spots = town() + [s]
        before = copy.deepcopy(spots)
        entries = osm.build_entries(spots, [food_poi(["สมบูรณ์โภชนา", "Somboon Seafood"], 1500)], "th")
        self.assertEqual(entries[osm.spot_key(s)], {"d": 2, "has": ["local_name", "local_primary"], "via": "area"})
        # licence: an area match never hands a spot coordinates (or anything else)
        self.assertEqual(spots, before)

    def test_holdout_counts_picks_near_the_truth(self):
        here = dict(spot("Somboon Seafood", lat=offset(1500)), dest="Chiang Mai", up=["Northern Thailand"])
        moved = dict(spot("Uncle Don's", lat=offset(100)), dest="Chiang Mai", up=["Northern Thailand"])
        pois = [food_poi(["Somboon Seafood"], 1550), food_poi(["Uncle Don's"], 1000)]  # 50 m vs 900 m off
        self.assertEqual(osm.area_holdout(town() + [here, moved], pois), (2, 1))
        self.assertEqual(here["lat"], offset(1500))  # the holdout hides coords on copies only

    def test_trust_needs_precision_and_volume(self):
        self.assertTrue(osm.area_trusted(100, 85))
        self.assertFalse(osm.area_trusted(100, 84))   # near-miss: KR measured 70 of 98
        self.assertFalse(osm.area_trusted(29, 29))    # near-miss: too few picks to judge

    def test_untrusted_country_gets_point_matches_only(self):
        s = lost("Somboon Seafood")
        entries = osm.build_entries(town() + [s], [food_poi(["Somboon Seafood"], 1500)], "th", use_area=False)
        self.assertEqual(entries, {})

    def test_area_cells_cover_the_disc(self):
        lat, lon, r = osm.areas(town())[("Chiang Mai", ("Northern Thailand",))]
        self.assertEqual(r, osm.AREA_MIN_R)
        cells = osm.area_cells([(lat, lon, r)])
        edge = lat + (r - 50) / 111_320.0
        self.assertIn((int(edge // osm.CELL), int(lon // osm.CELL)), cells)
        self.assertNotIn((int((lat + 3 * r / 111_320.0) // osm.CELL), int(lon // osm.CELL)), cells)


try:
    import osmium  # noqa: F401
    HAVE_OSMIUM = True
except ImportError:  # the main collect job does not install it; osm.yml does
    HAVE_OSMIUM = False

XML = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="{lat0}" lon="{lon}" version="1"><tag k="amenity" v="restaurant"/><tag k="name" v="ทองพูน"/><tag k="name:en" v="Thong Poon"/><tag k="opening_hours" v="10:00-20:00"/></node>
  <node id="2" lat="{lat1}" lon="{lon0}" version="1"/>
  <node id="3" lat="{lat1}" lon="{lon1}" version="1"/>
  <node id="4" lat="{lat2}" lon="{lon1}" version="1"/>
  <way id="10" version="1"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="2"/><tag k="amenity" v="cafe"/><tag k="name" v="Sapphic Riot"/></way>
  <node id="5" lat="{far}" lon="{lon}" version="1"><tag k="amenity" v="restaurant"/><tag k="name" v="Far Away"/></node>
  <node id="6" lat="{lat0}" lon="{lon}" version="1"><tag k="amenity" v="restaurant"/></node>
</osm>
"""


@unittest.skipUnless(HAVE_OSMIUM, "pyosmium not installed")
class ReadPoisTest(unittest.TestCase):
    def test_nodes_and_ways_near_spots_only(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "t.osm")
        with open(path, "w", encoding="utf-8") as f:
            f.write(XML.format(lat0=offset(9), lat1=offset(20), lat2=offset(40), far=offset(5000),
                               lon=TH_LON, lon0=TH_LON - 0.0002, lon1=TH_LON + 0.0002))
        pois = osm.read_pois(path, [spot("Thong Poon"), spot("Sapphic Riot", cat="cafes")])
        names = sorted(n for p in pois for n in p["names"])
        self.assertEqual(names, ["sapphic riot", "thong poon", "ทองพูน"])  # far node and unnamed node dropped
        entries = osm.build_entries([spot("Thong Poon"), spot("Sapphic Riot", cat="cafes")], pois, "th")
        self.assertEqual(sorted(e["d"] for e in entries.values()), [0, 3])  # hours + Thai name; bare cafe


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from ulu import signals
from ulu.build import attach_signals
from ulu.score import MIN_POOL, percentiles, ulu_scores


def spot(cat, **sig):
    return {"cat": cat, "signals": sig}


class WindowTest(unittest.TestCase):
    def test_last_twelve_full_months(self):
        self.assertEqual(signals.window(date(2026, 10, 14)), ("20251001", "20260930"))

    def test_january_wraps_the_year(self):
        self.assertEqual(signals.window(date(2026, 1, 1)), ("20250101", "20251231"))


class ShareTest(unittest.TestCase):
    def test_floor(self):
        self.assertIsNone(signals.share(150, 149))       # 299 views a year: noise
        self.assertEqual(signals.share(150, 150), 0.5)   # near-miss: exactly at the floor

    def test_local_only_article(self):
        self.assertEqual(signals.share(900, 0), 1.0)

    def test_title_slash_is_encoded(self):
        u = signals.pv_url("th", "AC/DC Bar", "20251001", "20260930")
        self.assertIn("/th.wikipedia/all-access/user/AC%2FDC_Bar/monthly/", u)


class PercentileTest(unittest.TestCase):
    def test_mid_rank_ties(self):
        p = percentiles([0.1, 0.5, 0.5, 0.9])
        self.assertEqual((p[0.1], p[0.5], p[0.9]), (0.125, 0.5, 0.875))

    def test_lone_value(self):
        self.assertEqual(percentiles([3]), {3: 0.5})


class UluTest(unittest.TestCase):
    def test_fame_alone_never_scores(self):
        s = [spot("sights", sitelinks=80)]
        ulu_scores(s, min_pool=1)
        self.assertIsNone(s[0]["ulu"])

    def test_no_signals_is_null_not_zero(self):
        s = [spot("dine")]
        ulu_scores(s, min_pool=1)
        self.assertIsNone(s[0]["ulu"])

    def test_missing_signal_renormalises(self):
        # sitelinks missing on b: its score must come from local_share alone, not be dragged to 0
        a, b = spot("sights", local_share=0.2, sitelinks=5), spot("sights", local_share=0.9)
        ulu_scores([a, b], min_pool=1)
        self.assertEqual(b["ulu"], 75)
        self.assertEqual(a["ulu"], round(100 * (0.4 * 0.25 + 0.15 * 0.5) / 0.55))

    def test_percentiles_are_per_category(self):
        a, b = spot("dine", local_share=0.1), spot("nature", local_share=0.9)
        ulu_scores([a, b], min_pool=1)
        self.assertEqual(a["ulu"], b["ulu"])  # each is alone in its category

    def test_small_pool_scores_nobody(self):
        pool = [spot("activities", local_share=i / 10) for i in range(MIN_POOL - 1)]
        ulu_scores(pool)
        self.assertTrue(all(s["ulu"] is None for s in pool))

    def test_pool_at_the_floor_scores(self):
        # near-miss: exactly MIN_POOL locality-scored spots is enough
        pool = [spot("activities", local_share=i / 10) for i in range(MIN_POOL)]
        ulu_scores(pool)
        self.assertTrue(all(isinstance(s["ulu"], int) for s in pool))

    def test_fame_only_spots_do_not_fill_the_pool(self):
        pool = [spot("activities", local_share=i / 10) for i in range(MIN_POOL - 1)]
        pool += [spot("activities", sitelinks=50) for _ in range(5)]
        ulu_scores(pool)
        self.assertTrue(all(s["ulu"] is None for s in pool))


class ConstantSignalTest(unittest.TestCase):
    def test_constant_locality_signal_scores_nobody(self):
        # Japan: every OSM name is Japanese, so osm_local = 1 for every matched spot
        pool = [spot("dine", osm_local=1) for _ in range(MIN_POOL + 5)]
        ulu_scores(pool)
        self.assertTrue(all(s["ulu"] is None for s in pool))

    def test_two_values_do_score(self):
        # near-miss: one spot without a local name is enough variation to rank on
        pool = [spot("dine", osm_local=1) for _ in range(MIN_POOL)] + [spot("dine", osm_local=0)]
        ulu_scores(pool)
        self.assertTrue(all(isinstance(s["ulu"], int) for s in pool))
        self.assertLess(pool[-1]["ulu"], pool[0]["ulu"])

    def test_constant_signal_does_not_mute_a_live_one(self):
        pool = [spot("dine", osm_local=1, local_share=i / 10) for i in range(MIN_POOL)]
        ulu_scores(pool)
        self.assertEqual(pool[-1]["ulu"], 95)  # local_share alone decides: top of 10 = 0.95


class AttachTest(unittest.TestCase):
    def test_absent_keys_mean_no_data(self):
        spots = [{"wd": "Q1", "score": 7}, {"wd": "Q2", "score": 3}, {"wd": "", "score": 0}]
        attach_signals(spots, {"Q1": {"local_views": 900, "en_views": 0, "local_share": 1.0, "local_only": True},
                               "Q2": {"local_views": 10, "en_views": 20, "local_share": None, "local_only": False}})
        self.assertEqual(spots[0]["signals"],
                         {"sitelinks": 7, "local_views": 900, "local_share": 1.0, "local_only": True})
        self.assertEqual(spots[1]["signals"], {"sitelinks": 3, "local_views": 10})
        self.assertEqual(spots[2]["signals"], {})
        self.assertTrue(all(s["listed_by"] == "wikivoyage" for s in spots))


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(ROOT, "config", name), encoding="utf-8") as f:
        return json.load(f)


class ConfigTest(unittest.TestCase):
    def test_every_country_has_platforms_that_exist(self):
        countries = load("countries.json")["countries"]
        plat = load("platforms.json")
        for c in countries:
            with self.subTest(cc=c["cc"]):
                conf = plat["countries"][c["cc"]]
                self.assertTrue(conf["dine"] and conf["any"] and conf["why"])
                for pid in conf["dine"] + conf["any"]:
                    self.assertIn(pid, plat["platforms"])

    def test_every_enabled_country_has_an_osm_extract(self):
        # a missing path silently drops signal D for that country; a typo 404s in CI
        for c in load("countries.json")["countries"]:
            if c["enabled"]:
                with self.subTest(cc=c["cc"]):
                    self.assertRegex(c.get("osm", ""), r"^(asia|europe|africa|north-america|south-america|"
                                                       r"central-america|australia-oceania)/[a-z0-9-]+$")

    def test_osm_score_needs_an_extract(self):
        for c in load("countries.json")["countries"]:
            if "osm_score" in c:
                with self.subTest(cc=c["cc"]):
                    self.assertIs(c["osm_score"], True)  # absent = off; never a string "false"
                    self.assertTrue(c.get("osm"))

    def test_templates(self):
        for pid, p in load("platforms.json")["platforms"].items():
            with self.subTest(pid=pid):
                self.assertIn("{q}", p["url"])
                self.assertTrue(p["url"].startswith("https://"))
                self.assertIn(p["query"], ("en", "local"))
                self.assertIn(p["verified"], ("ok", "challenge", "login"))
                # a {city} template without a cities map would never produce a link
                self.assertEqual("{city}" in p["url"], bool(p.get("cities")))
                if "mobile" in p:
                    # app.js only lets https and the xhsdiscover app scheme through
                    self.assertRegex(p["mobile"], r"^(https://|xhsdiscover://)")
                    self.assertTrue("{q}" in p["mobile"] or "{slug}" in p["mobile"])
                    self.assertNotIn("{city}", p["mobile"])

    def test_phone_templates_for_broken_mobile_web(self):
        # measured 2026-10-15: TikTok mobile web /search shows trending, XHS mobile web is a 404
        plat = load("platforms.json")["platforms"]
        self.assertEqual(plat["tiktok"]["mobile"], "https://www.tiktok.com/discover/{slug}")
        self.assertTrue(plat["xhs"]["mobile"].startswith("xhsdiscover://search/result?keyword="))
        self.assertEqual(plat["xhs"]["verified"], "login")  # desktop shows 登录后查看搜索结果


if __name__ == "__main__":
    unittest.main()

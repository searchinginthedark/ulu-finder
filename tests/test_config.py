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

    def test_templates(self):
        for pid, p in load("platforms.json")["platforms"].items():
            with self.subTest(pid=pid):
                self.assertIn("{q}", p["url"])
                self.assertTrue(p["url"].startswith("https://"))
                self.assertIn(p["query"], ("en", "local"))
                self.assertIn(p["verified"], ("ok", "challenge", "login"))
                # a {city} template without a cities map would never produce a link
                self.assertEqual("{city}" in p["url"], bool(p.get("cities")))


if __name__ == "__main__":
    unittest.main()

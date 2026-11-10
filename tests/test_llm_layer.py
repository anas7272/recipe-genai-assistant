"""Tests the LLM layer with a STUB provider (no Ollama / Gemini needed): planner JSON -> deterministic execution ->
summary verification.  Shows (a) a correct plan+summary is accepted, (b) a hallucinated summary is rejected and the
plain data is shown instead.   python -m unittest tests.test_llm_layer"""
import json, os, re, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from recipebot import llm, ingest, compose
from recipebot.chat import Bot

DB = os.path.join(tempfile.gettempdir(), "llm_test.db")
ingest.build(os.path.join(os.path.dirname(__file__), "fixture"), DB, quiet=True)

PLANS = {
 "what share of all recipes use onion and garlic together?": {"action": "stats", "stat": {"type": "count", "contains_all": ["onion", "garlic"]}},
 "show me something with penne": {"action": "search", "dish": "penne"},
 "no dairy please": {"action": "search", "exclude": ["dairy"]},
 "chicken": {"action": "names", "dish": "chicken"},
 "is it healthy? calories?": {"action": "unsupported", "attribute": "nutrition"},
 "garbage": {"action": "stats"},     # invalid plan (stats without a type) -> rule-based fallback
}

class Stub:
    mode = "good"
    def __call__(self, prompt, system=None, json_mode=False, timeout=0):
        if json_mode:
            msg = re.search(r"User message: (.*)\nJSON:", prompt).group(1)
            return json.dumps(PLANS[msg]) if msg in PLANS else None
        data = prompt.split("DATA:\n", 1)[1]
        if self.mode == "good":                      # copies numbers from DATA
            m = re.search(r"count = (\d+); percentage = [^=]*= ([\d.]+)%", data)
            return f"{m.group(1)} recipes match, which is {m.group(2)}% of the dataset." if m else "Here are the matching recipes."
        return "About 61% of recipes match, roughly 999 recipes, and each takes 20 minutes."   # hallucination

class T(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()
        self._g, self._a, self._l = llm.generate, llm.available, llm.last_provider
        llm.generate, llm.available, llm.last_provider = self.stub, (lambda: True), (lambda: "stub")
        os.environ["LLM_PROVIDER"] = "auto"
        self.bot = Bot(DB, use_llm=True)
    def tearDown(self):
        llm.generate, llm.available, llm.last_provider = self._g, self._a, self._l

    def test_percentage_is_computed_by_code_and_summary_verified(self):
        r = self.bot.reply("what share of all recipes use onion and garlic together?")
        self.assertIn("Recipes analysed", r); self.assertIn("percentage =", r); self.assertIn("verified", r)
        self.assertRegex(r.splitlines()[0], r"\d+ recipes match, which is [\d.]+% of the dataset")

    def test_hallucinated_summary_is_rejected(self):
        self.stub.mode = "bad"
        r = self.bot.reply("what share of all recipes use onion and garlic together?")
        self.assertNotIn("61%", r); self.assertNotIn("999", r); self.assertIn("rejected by the grounding check", r)
        self.assertIn("Recipes analysed", r)         # plain computed data still shown

    def test_followup_restriction_through_planner(self):
        self.bot.reply("show me something with penne")
        r = self.bot.reply("no dairy please")
        self.assertIn("no dairy", r)

    def test_percentage_of_chicken_dishes_is_a_computed_statistic(self):
        r = self.bot.reply("what percentage of recipes are chicken dishes?")
        self.assertIn("contains ALL of: chicken", r)
        self.assertIn("Calculation: count =", r)
        self.assertIn("percentage =", r)
        self.assertNotIn("Dish / title query", r)

    def test_share_statistics_work_without_llm(self):
        self.bot.use_llm = False
        r = self.bot.reply("what share of all recipes use onion and garlic together?")
        self.assertIn("contains ALL of: onion, garlic", r)
        self.assertIn("percentage =", r)

    def test_new_dish_updates_context_and_keeps_restrictions(self):
        self.bot.use_llm = False
        self.bot.reply("find penne pasta")
        self.bot.reply("no dairy")
        self.bot.reply("find tomato soup")
        self.bot.reply("with ingredients onion")

        self.assertEqual(self.bot.s.filters.dish, ["tomato", "soup"])
        self.assertEqual(self.bot.s.filters.include, ["onion"])
        self.assertEqual([e.key for e in self.bot.s.exclude], ["dairy"])
        self.assertIn("Quick Tomato Soup", self.bot._ctx())
        self.assertIn("find penne pasta", self.bot._ctx())
        self.assertIn("find tomato soup", self.bot._ctx())

    def test_names_and_unsupported_not_narrated(self):
        self.assertIn("dishes for 'chicken'", self.bot.reply("chicken"))
        self.assertIn("NO nutrition", self.bot.reply("is it healthy? calories?"))

    def test_invalid_plan_falls_back_to_rules(self):
        self.assertTrue(self.bot.reply("garbage"))

    def test_verify_function(self):
        data = "count = 7; percentage = 7 / 30 x 100 = 23.33%  [fn-p4]"
        self.assertEqual(compose.verify("7 recipes, 23.33%, see [fn-p4]", data), [])
        self.assertTrue(compose.verify("24% and 8 recipes [fn-zzz]", data))

if __name__ == "__main__": unittest.main()

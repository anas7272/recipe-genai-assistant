import unittest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from recipebot.normalize import parse_line, split_steps
from recipebot.restrict import check_line

def opts(line): return [e["opts"] for e in parse_line(line)]

class T(unittest.TestCase):
    def test_compound_split(self):   self.assertEqual(opts("Salt and freshly ground black pepper"), [["salt"], ["black pepper"]])
    def test_alternatives(self):     self.assertEqual(opts("1 cup butter or margarine, softened"), [["butter", "margarine"]])
    def test_quantity(self):
        e = parse_line("1 1/2 cups all-purpose flour")[0]; self.assertEqual((e["opts"], round(e["q"])), (["flour"], 360))
    def test_substring_traps(self):
        for l in ("1 eggplant", "Reggiano cheese", "veggie crumbles"): self.assertNotIn("egg", opts(l)[0] if opts(l) else [])
        self.assertEqual(opts("1 butternut squash"), [["butternut squash"]])
    def test_products_stay_different(self):
        self.assertEqual(opts("1 can tomato paste"), [["tomato paste"]]); self.assertEqual(opts("1/2 cup peanut butter"), [["peanut butter"]])
    def test_noise(self):
        for l in ("ADVERTISEMENT", "Special equipment: 8 skewers", "For the sauce:", "Preheat the grill"): self.assertEqual(parse_line(l), [])
    def test_dairy_exceptions(self):
        self.assertEqual(check_line("1 cup coconut milk", "dairy")[0], "exception")
        self.assertEqual(check_line("2 tbsp peanut butter", "dairy")[0], "exception")
        self.assertEqual(check_line("1 cup heavy cream", "dairy")[0], "violates")
        self.assertEqual(check_line("1 tsp cream of tartar", "dairy")[0], "exception")
    def test_steps(self):
        self.assertEqual(len(split_steps("Mix.\nBake.\n")), 2); self.assertEqual(len(split_steps("Mix well. Bake it. Serve.")), 3)

if __name__ == "__main__": unittest.main()

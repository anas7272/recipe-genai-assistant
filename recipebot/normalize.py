"""Ingredient-line parsing and normalisation.

parse_line("2 large eggs, beaten") -> [{"opts": ["egg"], "q": 2.0, "dim": "cnt", "unit": "", ...}]

* One raw line can yield several entries ("salt and pepper") .
* Each entry has `opts`: the primary canonical ingredient first, then alternatives
  ("butter or margarine" -> ["butter", "margarine"]).
* Whole-word regexes only (so "egg" never matches Reggiano / eggplant / veggie).
* Different products stay different: tomato != tomato paste, egg != egg white,
  peanut butter != butter, coconut milk != milk.
"""
import re
from functools import lru_cache

FRAC = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8", "⅜": "3/8"}

# ---------------------------------------------------------------- units
_U = {}


def _reg(names, dim, factor, canon):
    for n in names.split():
        _U[n] = (canon, dim, factor)


_reg("cup cups", "vol", 240, "cup")
_reg("tablespoon tablespoons tbsp tbsps tbs tbl", "vol", 15, "tbsp")
_reg("teaspoon teaspoons tsp tsps", "vol", 5, "tsp")
_reg("pint pints", "vol", 473, "pint")
_reg("quart quarts", "vol", 946, "quart")
_reg("gallon gallons", "vol", 3785, "gallon")
_reg("liter liters litre litres", "vol", 1000, "liter")
_reg("ml milliliter milliliters", "vol", 1, "ml")
_reg("ounce ounces oz", "wt", 28.35, "oz")
_reg("pound pounds lb lbs", "wt", 453.6, "lb")
_reg("gram grams g", "wt", 1, "g")
_reg("kg kilogram kilograms", "wt", 1000, "kg")
for _n in ("clove cloves can cans package packages pkg packet packets pinch pinches dash dashes slice "
           "slices stick sticks bunch bunches head heads sprig sprigs stalk stalks jar jars bottle "
           "bottles piece pieces handful container bag box envelope envelopes sheet sheets fillet "
           "fillets ear ears").split():
    _U[_n] = (re.sub(r"(?:es|s)$", "", _n) if _n.endswith(("ches", "shes")) else _n.rstrip("s"), "cnt", 1)

SIZE_WORDS = {"large", "medium", "small", "extra", "jumbo", "big", "heaping", "scant", "level", "generous"}

NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
QTY_RE = re.compile(rf"^\s*(?:about\s+|approximately\s+|approx\.?\s+)?({NUM})(?:\s*(?:-|–|to)\s*{NUM})?\s*")


def _num(s):
    s = s.strip()
    if " " in s:
        w, f = s.split(None, 1)
        return float(w) + _num(f)
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def _frac_fix(s):
    s = re.sub(r"(\d)\s*([¼½¾⅓⅔⅛⅜])", lambda m: f"{m.group(1)} {FRAC[m.group(2)]}", s)
    return re.sub(r"[¼½¾⅓⅔⅛⅜]", lambda m: FRAC[m.group(0)], s)


# ---------------------------------------------------------------- lexicon
# canon = regex.  Order matters only for ties at the same start position
# (leftmost match wins first, so "peanut butter" beats "butter" automatically).
LEX_SRC = r"""
tortilla = (?:corn |flour |whole wheat )?tortillas?
peanut butter = peanut butter
nut butter = (?:almond|cashew|hazelnut|sunflower(?: seed)?|nut|cocoa|coconut|apple) butter
lima bean = butter beans?
lettuce = butter(?:head)? lettuce
butternut squash = butternut(?: squash)?
buttermilk = buttermilk
egg noodle = egg noodles?
eggplant = egg ?plants?|aubergines?
egg white = egg whites?
egg yolk = egg yolks?
egg substitute = egg (?:substitute|replacer)|egg beaters
egg = eggs?
mayonnaise = mayonnaise|mayo
parmesan = parmesan|parmigiano|reggiano|parmigiano[- ]reggiano
mozzarella = mozzarella
cheddar = cheddar
feta = feta
ricotta = ricotta
cream cheese = cream cheese
cheese = cheeses?
sour cream = sour cream|soured cream
cream soup = cream of (?:mushroom|chicken|celery|potato) soup
cream of tartar = cream of tartar
coconut cream = coconut cream|cream of coconut
heavy cream = heavy (?:whipping )?cream|whipping cream|double cream
half and half = half[- ]and[- ]half
ice cream = ice cream
cream = cream
coconut milk = coconut milk
almond milk = almond milk
soy milk = soy ?milk|soymilk
oat milk = oat milk
evaporated milk = evaporated milk
condensed milk = (?:sweetened )?condensed milk
milk = milk
yogurt = yogh?urt
butter = butter
margarine = margarine
ghee = ghee
whole wheat flour = whole[- ]wheat flour|wholemeal flour
bread flour = bread flour
rice flour = rice flour
almond flour = almond (?:flour|meal)
coconut flour = coconut flour
cornmeal = cornmeal|polenta
cornstarch = corn ?starch|cornflour|corn flour
flour = flour
brown sugar = brown sugar
powdered sugar = confectioners'? ?sugar|powdered sugar|icing sugar
sugar = sugar
honey = honey
maple syrup = maple syrup
molasses = molasses
baking powder = baking powder
baking soda = baking soda|bicarbonate of soda
yeast = yeast
vanilla = vanilla(?: extract| bean)?
cocoa = cocoa(?: powder)?
chocolate = chocolate(?: chips?| chunks?)?
salt = (?:kosher |sea |table )?salt
red pepper flakes = (?:crushed )?red pepper flakes?
bell pepper = bell peppers?|sweet peppers?|capsicum|(?:green|red|yellow|orange) peppers?
chile = chil(?:e|i)(?:es|s)?|jalape[nñ]os?|serranos?|habaneros?|cayenne(?: pepper)?
black pepper = black pepper|white pepper|ground pepper|peppercorns?|pepper
paprika = paprika
cumin = cumin
cinnamon = cinnamon
nutmeg = nutmeg
ginger = ginger
oregano = oregano
basil = basil
thyme = thyme
rosemary = rosemary
parsley = parsley
cilantro = cilantro|coriander leaves
dill = dill
mint = mint
sage = sage
bay leaf = bay leaf|bay leaves
chives = chives?
garlic powder = garlic powder|garlic salt
garlic = garlic
onion powder = onion powder
green onion = green onions?|scallions?|spring onions?
shallot = shallots?
leek = leeks?
onion = onions?
tomato paste = tomato paste|tomato pur[eé]e
tomato sauce = tomato sauce|marinara|pasta sauce|spaghetti sauce
tomato = tomato(?:es)?
olive oil = olive oil
sesame oil = sesame oil
coconut oil = coconut oil
peanut oil = peanut oil
vegetable oil = (?:vegetable|canola|corn|sunflower|safflower|grapeseed|salad|cooking) oil
oil = oil
vinegar = vinegar
lemon juice = lemon juice
lemon = lemons?
lime juice = lime juice
lime = limes?
orange = oranges?
soy sauce = soy sauce|tamari|shoyu
fish sauce = fish sauce
worcestershire = worcestershire(?: sauce)?
hot sauce = hot sauce|tabasco|sriracha
mustard = mustard
ketchup = ketchup|catsup
chicken broth = chicken (?:stock|broth|bouillon)(?: cubes?)?
beef broth = beef (?:stock|broth|bouillon)(?: cubes?)?
vegetable broth = vegetable (?:stock|broth|bouillon)
water chestnut = water chestnuts?
coconut water = coconut water
water = water
red wine = red wine
white wine = white wine
wine = wine
beer = beer
chicken = chicken
beef = beef|steak|sirloin|brisket
pork = pork
bacon = bacon
ham = ham
sausage = sausages?
shrimp = shrimps?|prawns?
salmon = salmon
tuna = tuna
fish = fish
lamb = lamb
turkey = turkey
carrot = carrots?
celery = celery
sweet potato = sweet potatoes?|yams?
potato = potato(?:es)?
spinach = spinach
mushroom = mushrooms?
broccoli = broccoli
cauliflower = cauliflower
zucchini = zucchinis?|courgettes?
cucumber = cucumbers?
corn = corn
peas = (?:green |snow |sugar snap )?peas?
chickpea = chickpeas?|garbanzo(?: beans?)?
black bean = black beans?
kidney bean = kidney beans?
white bean = white beans?|cannellini(?: beans?)?
green bean = green beans?|string beans?
bean = beans?
lentil = lentils?
rice vinegar = rice vinegar
wild rice = wild rice
rice noodle = rice noodles?|rice vermicelli
rice = rice
penne = penne
spaghetti = spaghetti
macaroni = macaroni
fettuccine = fettuccine|fettucine
linguine = linguine
rigatoni = rigatoni
lasagna noodle = lasagn?a(?: noodles| sheets)?
orzo = orzo
pasta = pasta
noodle = noodles?
breadcrumbs = bread ?crumbs?|panko
bread = bread
oats = (?:rolled |old[- ]fashioned |quick )?oats?|oatmeal
applesauce = apple ?sauce
apple = apples?
banana = bananas?
raisin = raisins?
cranberry = cranberr(?:y|ies)
strawberry = strawberr(?:y|ies)
blueberry = blueberr(?:y|ies)
avocado = avocados?
walnut = walnuts?
almond = almonds?
pecan = pecans?
cashew = cashews?
pistachio = pistachios?
hazelnut = hazelnuts?
pine nut = pine nuts?
peanut = peanuts?
coconut = coconut
sesame seed = sesame seeds?
tahini = tahini
tofu = tofu
flaxseed = flax ?seeds?|flaxseed meal|flax meal
silken tofu = silken tofu
nutritional yeast = nutritional yeast
"""

LEX = []
for _line in LEX_SRC.strip().splitlines():
    _c, _rx = _line.split(" = ", 1)
    LEX.append((_c.strip(), _rx.strip()))
_LEX_RE = re.compile("|".join(rf"(?P<g{i}>\b(?:{rx})\b)" for i, (_, rx) in enumerate(LEX)))
_CANON_BY_GROUP = {f"g{i}": c for i, (c, _) in enumerate(LEX)}

PASTA_SHAPES = {"penne", "spaghetti", "macaroni", "fettuccine", "linguine", "rigatoni", "lasagna noodle", "orzo"}
OILS = {"olive oil", "sesame oil", "coconut oil", "peanut oil", "vegetable oil"}
CHEESES = {"parmesan", "mozzarella", "cheddar", "feta", "ricotta", "cream cheese"}

# have -> extra needs it also satisfies (one-directional: "egg" satisfies "egg white", not vice-versa)
IMPLIES = {"egg": {"egg white", "egg yolk"}, "heavy cream": {"cream"}, "half and half": {"cream"},
           "chicken broth": {"broth"}, "beef broth": {"broth"}, "vegetable broth": {"broth"}}
for _p in PASTA_SHAPES:
    IMPLIES.setdefault(_p, set()).add("pasta")
for _o in OILS:
    IMPLIES.setdefault(_o, set()).add("oil")
for _c in CHEESES:
    IMPLIES.setdefault(_c, set()).add("cheese")

STAPLES = {"salt", "water", "black pepper"}  # assumed available by the matcher (reported, never hidden)

NOISE = re.compile(r"^\s*(?:special )?equipment\b|^\s*you will need|^\s*preheat|\b(?:toothpicks?|skewers?|cheesecloth|"
                   r"kitchen twine|butcher'?s twine|thermometer|aluminum foil|parchment paper)\b")

DESC = set("""fresh freshly finely coarsely roughly chopped minced diced sliced grated shredded crushed peeled seeded cored
trimmed halved quartered cubed melted softened packed divided optional thinly lightly beaten large medium small extra
jumbo ripe firm boneless skinless cooked uncooked raw about approximately more less a an the of for to taste plus and
with without in into from your own good quality unsalted salted hot cold warm room temperature low-sodium reduced-fat
fat-free skim lowfat nonfat low-fat big heaping scant level generous drained rinsed thawed frozen canned toasted
ground lean""".split())

TRAIL = re.compile(r"\b(?:to taste|for (?:serving|garnish|dusting|greasing|sprinkling|brushing|frying|the)\b.*|as needed|"
                   r"optional|divided|plus more.*|plus extra.*|or more.*|if desired|if needed|at room temperature)\s*$")
BAD_ALT_START = ("more", "less", "to ", "as ", "a bit", "until", "if ", "so ", "for ")


def sing(w):
    if len(w) <= 3:
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "oes", "sses", "xes")):
        return w[:-2]
    if w.endswith(("ss", "us")):
        return w
    return w[:-1] if w.endswith("s") else w


def lex_match(text):
    m = _LEX_RE.search(text)
    return _CANON_BY_GROUP[m.lastgroup] if m else None


def generic(text):
    words = [w for w in re.findall(r"[a-z][a-z'\-]*", text) if w not in DESC]
    if not words:
        return None
    words = words[-3:]
    words[-1] = sing(words[-1])
    return " ".join(words)


def split_and(s):
    if " and " in s:
        left, right = s.split(" and ", 1)
        a, b = lex_match(left), lex_match(right)
        if a and b and a != b:
            return [left] + split_and(right)
    return [s]


@lru_cache(maxsize=500000)
def _resolve(text):
    """text (no quantity/unit) -> tuple of option-tuples, e.g. (('salt',), ('black pepper',))"""
    t = TRAIL.sub("", text.strip(" ,.;-–")).strip()
    if not t:
        return ()
    alts = [p for p in re.split(r"\s+or\s+", t) if p.strip()]
    comps = split_and(alts[0])
    out = []
    for ci, comp in enumerate(comps):
        c = lex_match(comp) or generic(comp)
        if not c:
            continue
        opts = [c]
        if ci == len(comps) - 1:
            for a in alts[1:]:
                a = a.strip()
                if a.startswith(BAD_ALT_START):
                    continue
                ac = lex_match(a) or (generic(a) if len(a.split()) <= 3 else None)
                if ac and ac not in opts:
                    opts.append(ac)
        out.append(tuple(opts))
    return tuple(out)


def _take_unit(s):
    words, unit, dim, factor = s.split(), "", None, 1
    while words:
        w = words[0].strip(".,")
        if w in SIZE_WORDS:
            words = words[1:]
        elif w in _U:
            if not unit:
                unit, dim, factor = _U[w]
            words = words[1:]
        else:
            break
    if words and words[0] == "of":
        words = words[1:]
    return unit, dim, factor, " ".join(words)


def parse_line(raw):
    """-> list of entry dicts (empty for headings / equipment / blank)."""
    s0 = (raw or "").lower().strip()
    if not s0 or s0 == "advertisement" or s0.endswith(":") or NOISE.search(s0):
        return []
    s = re.sub(r"\([^)]*\)", " ", s0)
    s = _frac_fix(s)
    qty = None
    m = QTY_RE.match(s)
    if m:
        qty, s = _num(m.group(1)), s[m.end():]
    else:
        m2 = re.match(r"^\s*(?:an?|one)\s+(?=\w)", s)
        if m2:
            qty, s = 1.0, s[m2.end():]
    unit, dim, factor, rest = _take_unit(s)
    if qty is not None and not unit:
        dim, unit = "cnt", ""
    if dim in ("vol", "wt") and qty is not None:
        base = qty * factor
    else:
        base = qty
    optional = "optional" in s0
    entries = []
    for opts in _resolve(rest.split(",")[0]):
        e = {"opts": list(opts), "q": base, "dim": dim, "unit": unit}
        if optional:
            e["o"] = 1
        entries.append(e)
    return entries


def satisfies(have, need):
    return have == need or need in IMPLIES.get(have, ())


def split_steps(text):
    """Step-counting rule: non-empty lines; if the text is one paragraph, sentences."""
    if not text:
        return []
    lines = [l.strip() for l in re.split(r"[\r\n]+", text) if l.strip()]
    if len(lines) == 1:
        sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", lines[0]) if x.strip()]
        return sents or lines
    return lines


def fmt_qty(x):
    """0.25 -> '1/4', 1.5 -> '1 1/2'"""
    fr = {0.125: "1/8", 0.25: "1/4", 0.333: "1/3", 0.5: "1/2", 0.667: "2/3", 0.75: "3/4"}
    whole, part = int(x), round(x - int(x), 3)
    best = min(fr, key=lambda k: abs(k - part)) if part else None
    if part and abs(best - part) < 0.02:
        return (f"{whole} " if whole else "") + fr[best]
    if part and not whole:
        return f"{x:.2f}".rstrip("0")
    return str(whole) if not part else f"{x:.2f}".rstrip("0")

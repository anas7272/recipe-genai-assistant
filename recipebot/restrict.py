"""Dietary / allergen restriction lexicons.

Deliberately CONSERVATIVE and text-based (whole-word regex on the raw ingredient line):
  violates  -> a term matched (recipe is excluded)
  caution   -> ingredient *may* contain the allergen (shown to the user, recipe kept)
  exception -> a dairy-like word that is actually non-dairy (coconut milk, peanut butter) -> shown as evidence
This is a text heuristic, NOT a medical safety guarantee.
"""
import re
from dataclasses import dataclass

W = lambda s: re.compile(rf"\b(?:{s})\b")

_MEAT = r"chicken|turkey|lamb|duck|goose|venison|rabbit|meatballs?|sausages?|hot dogs?|beef|steak|brisket|veal|sirloin|pork|bacon|ham|prosciutto|pancetta|lard|salami|pepperoni|chorizo"
_FISH = r"fish|salmon|tuna|cod|tilapia|halibut|trout|anchov(?:y|ies)|sardines?|mackerel|haddock|snapper|sea bass|swordfish|catfish|herring|fish sauce|caviar|roe"
_SHELL = r"shrimps?|prawns?|crabs?|crabmeat|lobsters?|crawfish|crayfish|clams?|mussels?|oysters?|scallops?|squid|calamari|shellfish|octopus"
_DAIRY = (r"milk|butter|cream|cheese|cheeses|yogh?urt|ghee|whey|casein|kefir|mascarpone|ricotta|parmesan|parmigiano|"
          r"reggiano|mozzarella|cheddar|feta|paneer|half[- ]and[- ]half|cr[eè]me fra[iî]che|custard|lactose|gruy[eè]re|"
          r"brie|gouda|provolone|buttermilk|ice cream|gelato")
_DAIRY_EXC = (r"coconut milk|almond milk|soy ?milk|oat milk|rice milk|cashew milk|hemp milk|peanut butter|"
              r"(?:almond|cashew|nut|cocoa|coconut|apple|sunflower seed|hazelnut) butter|coconut cream|cream of coconut|"
              r"cream of tartar|butternut|butter beans?|butter(?:head)? lettuce|non-?dairy|dairy[- ]free|"
              r"vegan (?:butter|cheese)|plant[- ]based (?:milk|butter)")
_EGG = r"eggs?|egg whites?|egg yolks?|mayonnaise|mayo|eggnog|meringue|aioli|hollandaise"
_GLUTEN = (r"wheat|flour|bread|breadcrumbs?|bread ?crumbs|panko|pasta|spaghetti|penne|macaroni|fettuccine|linguine|"
           r"lasagn[ae]|rigatoni|noodles?|couscous|barley|rye|semolina|bulgur|farro|seitan|soy sauce|beer|crackers?|pita|"
           r"tortillas?|pie crust|pizza dough|biscuits?|cake mix|croutons?|orzo|udon|ramen|malt|spelt|cookies?|graham")

CATS = {
    "dairy": dict(terms=_DAIRY, exc=_DAIRY_EXC, caution=r"chocolate|margarine|caramel|bread|marshmallows?"),
    "egg": dict(terms=_EGG, exc=r"eggplants?|egg[- ]free", caution=r"noodles?|marshmallows?|brioche|challah|egg substitute|fresh pasta"),
    "gluten": dict(terms=_GLUTEN,
                   exc=r"rice flour|almond flour|coconut flour|corn flour|cornflour|chickpea flour|gluten[- ]free|rice noodles?|"
                       r"corn tortillas?|buckwheat noodles?|potato flour|tapioca flour|almond meal",
                   caution=r"oats?|oatmeal|oat flour|tamari|worcestershire|broth|stock|bouillon|sausages?"),
    "peanut": dict(terms=r"peanuts?|peanut butter|peanut oil|groundnuts?|arachis", exc=r"peanut[- ]free",
                   caution=r"mixed nuts|satay|nuts|nut butter"),
    "tree_nut": dict(terms=r"almonds?|walnuts?|pecans?|cashews?|pistachios?|hazelnuts?|macadamias?|brazil nuts?|pine nuts?|"
                           r"pralines?|marzipan|nutella|chestnuts?|nuts|filberts?|nut butter|amaretto|frangelico",
                     exc=r"water chestnuts?|nut[- ]free|butternut", caution=r"coconut|mixed nuts"),
    "shellfish": dict(terms=_SHELL, exc=r"crab apples?", caution=r"fish sauce|oyster sauce"),
    "fish": dict(terms=_FISH, exc=r"fish[- ]free", caution=r"worcestershire|caesar|dashi|bonito"),
    "soy": dict(terms=r"soy|soya|soybeans?|soy ?milk|soy sauce|tofu|tempeh|edamame|miso|tamari|shoyu",
                exc=r"soy[- ]free", caution=r"margarine|bouillon"),
    "sesame": dict(terms=r"sesame|tahini|gomasio", exc=r"sesame[- ]free", caution=r""),
    "pork": dict(terms=r"pork|bacon|ham|prosciutto|pancetta|lard|salt pork|ham hock|guanciale|chorizo|salami|pepperoni",
                 exc=r"", caution=r"sausages?|gelatin|hot dogs?|bologna|ribs?"),
    "beef": dict(terms=r"beef|steak|brisket|veal|sirloin|ground chuck|corned beef", exc=r"",
                 caution=r"gelatin|bouillon|stock|broth|worcestershire"),
    "alcohol": dict(terms=r"wine|beer|vodka|rum|bourbon|whiske?y|brandy|liqueur|sherry|sake|mirin|champagne|tequila|gin|"
                          r"cognac|vermouth|ale|amaretto|kahlua|kirsch|marsala|stout|lager",
                    exc=r"wine vinegar|rice wine vinegar|non-?alcoholic|ginger ale|ginger beer|root beer", caution=r"vanilla extract"),
}
CATS["meat"] = dict(terms=_MEAT + "|" + _FISH + "|" + _SHELL, exc=r"", caution=r"gelatin|broth|stock|bouillon|worcestershire|rennet")
CATS["vegetarian"] = CATS["meat"]
CATS["vegan"] = dict(terms=CATS["meat"]["terms"] + "|" + _DAIRY + "|" + _EGG + "|honey|gelatin", exc=_DAIRY_EXC + "|eggplants?",
                     caution=r"margarine|wine|beer|chocolate|worcestershire|broth|stock|bouillon")
CATS["nut_free"] = dict(terms=CATS["peanut"]["terms"] + "|" + CATS["tree_nut"]["terms"], exc=CATS["tree_nut"]["exc"],
                        caution=r"coconut|mixed nuts|satay")
_C = {k: (W(v["terms"]), W(v["exc"]) if v["exc"] else None, W(v["caution"]) if v["caution"] else None) for k, v in CATS.items()}

ALIASES = {"dairy": "dairy", "lactose": "dairy", "milk products": "dairy", "gluten": "gluten", "wheat": "gluten",
           "egg": "egg", "eggs": "egg", "peanut": "peanut", "peanuts": "peanut", "tree nut": "tree_nut", "tree nuts": "tree_nut",
           "nut": "nut_free", "nuts": "nut_free", "shellfish": "shellfish", "fish": "fish", "soy": "soy", "soya": "soy",
           "sesame": "sesame", "pork": "pork", "beef": "beef", "meat": "meat", "vegetarian": "vegetarian", "vegan": "vegan",
           "alcohol": "alcohol", "nut allergy": "nut_free", "gluten-free": "gluten", "dairy-free": "dairy"}
LABEL = {"tree_nut": "tree nuts", "nut_free": "nuts (peanuts + tree nuts)", "meat": "meat/fish (vegetarian)"}


@dataclass(frozen=True)
class Exclusion:
    kind: str   # "cat" or "ing"
    key: str    # category name or canonical ingredient
    label: str

    def __str__(self):
        return self.label


def resolve_exclusion(token):
    from .normalize import parse_line
    t = token.strip().lower()
    t = re.sub(r"^(?:any|the|all|some|anything with|anything containing)\s+", "", t).strip(" .")
    if t in ALIASES:
        k = ALIASES[t]
        return Exclusion("cat", k, f"no {LABEL.get(k, k)}")
    e = parse_line(t)
    if e:
        return Exclusion("ing", e[0]["opts"][0], f"no {e[0]['opts'][0]}")
    return None


def check_line(line, cat):
    """-> ('violates'|'caution'|'exception'|None, matched_text)"""
    low = line.lower()
    terms, exc, caution = _C[cat]
    stripped = exc.sub(" ", low) if exc else low
    m = terms.search(stripped)
    if m:
        return "violates", m.group(0)
    if exc:
        me = exc.search(low)
        if me and terms.search(low):   # a dairy-like word that was exempted
            return "exception", me.group(0)
    if caution:
        mc = caution.search(low)
        if mc:
            return "caution", mc.group(0)
    return None, ""


def audit(lines, parsed, exclusions):
    """Returns dict with 'violations', 'cautions', 'exceptions' lists of (exclusion_label, raw_line, matched)."""
    out = {"violations": [], "cautions": [], "exceptions": []}
    for ex in exclusions:
        if ex.kind == "cat":
            for ln in lines:
                st, txt = check_line(ln, ex.key)
                if st == "violates":
                    out["violations"].append((ex.label, ln, txt))
                elif st == "caution":
                    out["cautions"].append((ex.label, ln, txt))
                elif st == "exception":
                    out["exceptions"].append((ex.label, ln, txt))
        else:
            for e in parsed:
                if ex.key in e["opts"]:
                    i = e.get("i")
                    ln = lines[i] if i is not None and i < len(lines) else ex.key
                    out["violations"].append((ex.label, ln, ex.key))
    return out

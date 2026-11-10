"""Rule-based language understanding (deterministic, testable). An optional LLM only handles messages
these rules cannot place (see llm.py)."""
import re
from .normalize import parse_line
from .restrict import resolve_exclusion, ALIASES

NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "twelve": 12, "fifteen": 15, "twenty": 20}
ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "fifth": 5}
CMD = set("""find show give suggest recommend search list get me a an the some any please can you could would i want need
like looking look for recipe recipes dish dishes something anything to make cook with what is are of that which have has
my us let s lets try also another other more and or but it this those these one ones just only too exclude excluding now then how do does hi hello hey thanks thank ok okay yes no sure""".split())
STOP_CLAUSE = re.compile(r"\b(?:but|and i\b|and at|and no|and prefer|and with|at most|at least|under|fewer|less than|with|using|"
                         r"that|which|in|for|please|too|as well|also|prefer|suggest|find|show)\b|[.?!;]")
TRIG = re.compile(r"(?:\bno\b|\bwithout\b|\bexclude\b|\bexcluding\b|\bavoid\b|\bskip\b|\bnot (?:include|use)\b|allergic to|"
                  r"allergy to|intolerant to|cannot (?:have|eat|tolerate|use)|can't (?:have|eat|tolerate|use)|cant (?:have|eat)|"
                  r"don't (?:eat|want|like|have)|do not (?:eat|want|like|have)|free of|(?:i )?(?:am|i'm) allergic to)\s+")
FREE = re.compile(r"\b(dairy|gluten|nut|egg|soy|lactose|sesame|peanut|shellfish|fish|alcohol|pork|meat)[- ]free\b")
ALLOW = re.compile(r"(?:i can (?:now )?(?:have|eat)|allow|(?:it'?s |is |are )?(?:fine|ok|okay) (?:with|to have)|drop the|ignore the|remove the|never ?mind(?: the)?)\s+([a-z ]+?)(?: restriction| again|$|[.,?!])"
                   r"|\b([a-z]+) (?:is|are) (?:fine|ok|okay)\b")


def _split_list(s):
    parts = re.split(r",|&|\band\b|\bor\b|/", s)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _clean_item(p):
    p = re.sub(r"\b(?:both|either|any|the|some|all|of|more|extra)\b", " ", p).strip()
    return re.sub(r"\s+", " ", p)


def extract_exclusions(t):
    out = []
    for m in TRIG.finditer(t):
        tail = t[m.end():]
        s = STOP_CLAUSE.search(tail)
        tail = tail[:s.start()] if s else tail
        for item in _split_list(tail):
            ex = resolve_exclusion(_clean_item(item)) if _clean_item(item) else None
            if ex and ex not in out:
                out.append(ex)
    for m in FREE.finditer(t):
        ex = resolve_exclusion(m.group(1) + ("" if m.group(1) in ALIASES else ""))
        if ex and ex not in out:
            out.append(ex)
    for w in ("vegetarian", "vegan"):
        if re.search(rf"(?<!non[- ]){w}", t):
            ex = resolve_exclusion(w)
            if ex not in out:
                out.append(ex)
    return out


def extract_allow(t):
    out = []
    for m in ALLOW.finditer(t):
        w = (m.group(1) or m.group(2) or "").strip()
        if w:
            ex = resolve_exclusion(w)
            if ex:
                out.append(ex)
    return out


def extract_max_steps(t):
    for rx in (r"(?:at most|no more than|under|fewer than|less than|max(?:imum)?(?: of)?|up to|within|below)\s+(\w+)\s+(?:\w+\s+)?steps?",
               r"(\w+)\s+(?:\w+\s+)?steps?\s+or\s+(?:fewer|less)", r"in\s+(\w+)\s+steps?\s+or"):
        m = re.search(rx, t)
        if m:
            v = m.group(1)
            n = int(v) if v.isdigit() else NUMW.get(v)
            if n:
                if "fewer than" in m.group(0) or "less than" in m.group(0) or m.group(0).startswith(("under", "below")):
                    n -= 1
                return n
    return None


def extract_top_n(t, default=5):
    m = re.search(r"\b(?:top|which|show|list|give me|suggest|find|recommend|me)\s+(\d+|" + "|".join(NUMW) + r")\b", t)
    if m:
        v = m.group(1)
        return int(v) if v.isdigit() else NUMW[v]
    return default


def extract_ids(t):
    return re.findall(r"\b((?:ar|epi|fn)-[0-9a-z_]+)\b", t)


def extract_ordinal(t):
    m = re.search(r"(?:#|number |no\.? |recipe |option |result |the )(\d)\b", t)
    if m:
        return int(m.group(1))
    for w, n in ORD.items():
        if re.search(rf"\b{w}\b", t):
            return n
    return None


def ingredients_from(text):
    """'garlic and onion' -> ['garlic','onion'] (canonical)."""
    out = []
    for item in _split_list(text):
        item = _clean_item(item)
        if not item or item.startswith(("no ", "without ")):
            continue
        e = parse_line(item)
        if e and e[0]["opts"][0] not in out:
            out.append(e[0]["opts"][0])
    return out


def extract_include(t, plain_with=False):
    """Ingredients the user REQUIRES.  For dish searches a plain "with" is part of the dish name
    ("Chicken Milanesa With Maggi Ranch Sauce"); only "with ingredients X", "containing X", "using X" ... count.
    Statistics questions ("recipes with tomato") pass plain_with=True."""
    out = []
    w = r"with(?:\s+(?:the|these|those))?\s+ingredients?\s*:?|with" if plain_with else r"with(?:\s+(?:the|these|those))?\s+ingredients?\s*:?"
    for m in re.finditer(rf"\b(?:{w}|containing|contain|contains|using|that (?:has|have|use|uses)|includes?|including|both)\s+(.+)", t):
        tail = m.group(1)
        s = re.search(r"\b(?:without|no|but|at most|under|fewer|less than|that|which|for|in|please|too|suggest|find|show)\b|[.?!;]", tail)
        tail = tail[:s.start()] if s else tail
        for c in ingredients_from(tail):
            if c not in out:
                out.append(c)
    return out


def extract_dish(t):
    s = t
    while True:                                   # drop "no/without/cannot have ..." clauses
        m = TRIG.search(s)
        if not m:
            break
        tail = s[m.end():]
        sm = STOP_CLAUSE.search(tail)
        s = s[:m.start()] + " " + tail[(sm.start() if sm else len(tail)):]
    s = FREE.sub(" ", s)
    s = re.sub(r"\b\w+-free\b|\bvegetarian\b|\bvegan\b|\bmake\b", " ", s)
    for rx in (r"\bwith\s+(?:the\s+|these\s+|those\s+)?ingredients?\b.*", r"\b(?:containing|using|that|which|but|and at|at most|under|fewer than|less than)\b.*", r"[.?!;].*"):
        s = re.sub(rx, " ", s)
    toks = [w for w in re.findall(r"[a-z][a-z'\-]+", s) if w not in CMD]
    return toks[:8]


def parse_have(t):
    """'I have 3 eggs, onions and 2 cups rice ...' -> list of parsed entries (canon, qty...) """
    m = re.search(r"(?:\bi (?:only |just )?have\b|\bi've got\b|\bi got\b|\bi also have\b|\balso have\b|\bhave got\b|\bwith these\b:?|\bingredients:)\s+(.+?)(?=[.?!]|\bsuggest\b|\bfind\b|\bgive\b|\bshow\b|\bwhat\b|\bcan you\b|\bplease\b|\bwith no\b|\bno \w+\b|\bat most\b|\bprefer\b|\busing as\b|$)", t)
    if not m:
        return []
    out = []
    for item in _split_list(m.group(1)):
        for e in parse_line(item):
            if e["opts"] and e["opts"][0] not in [x["opts"][0] for x in out]:
                out.append(e)
    return out


def prefer(t):
    if re.search(r"fewest (?:additional|missing|extra)|fewer (?:additional|missing)|least (?:additional|missing)|minimi[sz]e missing", t):
        return "missing"
    if re.search(r"fewest steps|fewer steps|quick|fastest|simplest|prefer (?:short|few)", t):
        return "steps"
    return "balanced"

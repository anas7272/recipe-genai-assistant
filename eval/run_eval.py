"""Reproducible evaluation.  Every expectation is computed by an INDEPENDENT oracle that reads the raw JSON files with
plain regexes (no recipebot parser/lexicon), then compared with what the chatbot answers.

  python eval/run_eval.py                       # builds a DB from tests/fixture and runs everything
  python eval/run_eval.py --data-dir data --db data/recipes.db   # same checks on the real dataset (oracle counts are
                                                                  # then expected to differ slightly where forms differ - see notes)
Writes eval/results.md.
"""
import argparse, json, os, re, sys, glob, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from recipebot import ingest, db
from recipebot.chat import Bot
from recipebot.normalize import parse_line

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", default="tests/fixture")
ap.add_argument("--db", default=os.path.join(tempfile.gettempdir(), "eval_recipes.db"))
a = ap.parse_args()
if a.data_dir == "tests/fixture" or not os.path.exists(a.db):
    ingest.build(a.data_dir, a.db, quiet=True)

# ---------------------------------------------------------------- oracle (independent of recipebot)
def load():
    recs, seen = {}, set()
    for src, f in ingest.SOURCES.items():
        for key, r in json.load(open(os.path.join(a.data_dir, f), encoding="utf-8")).items():
            lines = [x.strip() for x in (r.get("ingredients") or []) if x and x.strip() and x.strip().upper() != "ADVERTISEMENT"]
            steps = [x for x in re.split(r"[\r\n]+", r.get("instructions") or "") if x.strip()]
            if not (r.get("title") or "").strip() or not lines or not steps:
                continue
            sig = (r["title"].strip().lower(), tuple(sorted(l.lower() for l in lines)))
            if sig in seen:
                continue
            seen.add(sig)
            recs[f"{src}-{key}"] = dict(title=r["title"], lines=lines, steps=len(steps))
    return recs
O = load()
has = lambda r, rx: any(re.search(rx, l.lower()) for l in r["lines"])
TOM = r"\btomato(es)?\b(?!\s+(sauce|paste|pur))"   # documented rule: tomato sauce/paste/puree are different products
DAIRY = r"\b(milk|cream|butter|cheese|parmesan|parmigiano|reggiano|yogurt)\b"
nondairy = lambda l: re.sub(r"coconut milk|coconut cream|peanut butter", "", l.lower())
has_dairy = lambda r: any(re.search(DAIRY, nondairy(l)) for l in r["lines"])
ids_in = lambda text: re.findall(r"(?:Recipe ID:\*\*\s*`|\[)((?:ar|epi|fn)-[^\s`\]]+)(?:`|\])", text)

results = []
def case(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  -- {detail}" if detail and not ok else ""))

# ---------------------------------------------------------------- cases
bot = Bot(a.db, use_llm=False)

r = bot.reply("Find a penne pasta recipe.")
r = bot.reply("I cannot have dairy.")
shown = set(ids_in(r))
expect = {i for i, x in O.items() if re.search(r"\bpenne\b", x["title"].lower()) and not has_dairy(x)}
case("T1 follow-up: dairy restriction refines the active penne search (complete + sound vs oracle)", shown == expect,
     f"bot={sorted(shown)} oracle={sorted(expect)}")
case("T1 evidence: exempted 'coconut milk' is explained, not silently accepted",
     "coconut milk" in r.lower() and "allowed form" in r.lower())
r = bot.reply("Now find a tomato soup recipe.")
case("T1 restriction persists when the dish changes", "no dairy" in r)
bot.reply("reset")

r = bot.reply("How many recipes contain both garlic and onion? What percentage of the dataset is that?")
n = sum(1 for x in O.values() if has(x, r"\bgarlic\b") and has(x, r"\bonions?\b"))
case("T1 aggregate: count garlic AND onion equals oracle", f"count = {n};" in r and f"/ {len(O):,}" in r, f"oracle={n}/{len(O)}")
case("T1 aggregate states filter, N analysed, denominator and normalisation", all(k in r for k in ("Filter:", "Recipes analysed", "denominator", "Normalisation")))

r = bot.reply("Among recipes containing tomato, which five have the fewest instruction steps?")
cand = sorted(((x["steps"], i) for i, x in O.items() if has(x, TOM)))[:5]
case("T1 ranking: five fewest-step tomato recipes equal oracle (ties by ID)", ids_in(r) == [i for _, i in cand], f"bot={ids_in(r)} oracle={[i for _, i in cand]}")

r = bot.reply("What is the median number of ingredients in recipes containing tomato?")
xs = sorted(len(x["lines"]) for x in O.values() if has(x, TOM))
med = (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)
case("T1 median ingredient count equals oracle", abs(float(re.search(r"median = ([\d.]+)", r).group(1)) - med) < 1e-9, f"oracle median={med}")

bot.reply("find banana bread")
r = bot.reply("How many calories does it have, and how long does it take?")
case("T1 refuses attributes the data lacks (nutrition / cooking time) instead of estimating", "NO nutrition" in r and not re.search(r"\d+\s*(kcal|calories)", r.split("NO nutrition")[0]))
bot.reply("reset")

q = "I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as possible, with no peanuts and at most six instruction steps. Prefer recipes that need the fewest additional ingredients."
r = bot.reply(q)
ids = ids_in(r)
case("T2 hard constraints: every result has <=6 steps and no peanut", ids and all(O[i]["steps"] <= 6 and not has(O[i], r"\bpeanuts?\b") for i in ids))
case("T2 output shows matched / missing / why for each result", r.count("matched:") == len(ids) and r.count("missing / extra required:") == len(ids) and r.count("why:") == len(ids))
r = bot.reply("Exclude eggs too.")
ids = ids_in(r)
case("T2 follow-up 'Exclude eggs too' removes every egg recipe (oracle check, incl. whole-word 'egg')", ids and not any(has(O[i], r"\beggs?\b") for i in ids))
bot.reply("reset")
r = bot.reply("I have rice and tomatoes. Suggest recipes with at most 1 steps.")
case("T2 no-match case: says no match, flags violators, never presents them as eligible", "NO MATCH FOUND" in r and "VIOLATES YOUR CONSTRAINTS" in r and not any(O[i]["steps"] <= 1 for i in ids_in(r)))
r = bot.reply("I have 3 eggs, 1 onion, 2 cups rice and 1 tomato. Suggest 2 recipes")
case("T2 quantities: compared when units are comparable, else reported as name-level", "[enough]" in r or "SHORT" in r)

bot.reply("reset")
r = bot.reply("Take the banana bread recipe and remove eggs. Use only ingredients that appear in the dataset.")
case("T3 cites local recipe IDs as evidence and labels predictions", all(term in r.lower() for term in ("direct evidence", "indirect evidence", "prediction")) and re.search(r"(ar|epi|fn)-b\d", r))
updated_parts = r.split("## Updated ingredient list", 1)
updated = updated_parts[1].split("## Revised instructions", 1)[0] if len(updated_parts) == 2 else ""
updated_ingredients = [line.split("— **replaces:**", 1)[0] for line in updated.splitlines() if line.startswith("- ")]
case("T3 returns an updated ingredient list AND revised instructions, no eggs left",
     bool(updated_ingredients) and "## Revised instructions" in r and not any(re.search(r"\beggs?\b", line.lower()) for line in updated_ingredients))
r = bot.reply("use flaxseed")
case("T3 weak evidence is flagged (flaxseed has no similar-recipe support in the sample)",
     "none local support" in r.lower() and "no similar-recipe evidence" in r.lower())
bot.reply("reset")
r = bot.reply("Replace cream in this penne recipe without dairy.")
case("T3 reports remaining dairy (butter/parmesan) after replacing cream - no false 'safe' claim",
     "conflicts remain" in r.lower() and re.search(r"parmesan|parmigiano", r.lower()) and "butter" in r.lower())
r = bot.reply("replace vanilla in the banana bread recipe")
case("T3 refuses an ingredient it has no role knowledge for rather than inventing a substitute", "will not invent" in r)

# ---------------------------------------------------------------- ingestion / normalisation unit checks
con = db.connect(a.db)
t = db.totals(con)
raw = sum(len(json.load(open(os.path.join(a.data_dir, f), encoding="utf-8"))) for f in ingest.SOURCES.values())
case("Ingest: uses all three files; raw = valid + invalid; unique = oracle count", t["raw"] == raw and t["unique_valid"] == len(O), f"db={t} oracle_unique={len(O)} raw={raw}")
trap = {"1 eggplant": "egg", "1/2 cup Reggiano cheese": "egg", "veggie burgers": "egg", "2 large eggs, beaten": "egg"}
got = {k: [c for e in parse_line(k) for c in e["opts"]] for k in trap}
case("Normalisation traps: 'egg' not matched inside eggplant/Reggiano/veggie, but matched in 'eggs'",
     "egg" not in got["1 eggplant"] and "egg" not in got["1/2 cup Reggiano cheese"] and "egg" not in got["veggie burgers"] and got["2 large eggs, beaten"] == ["egg"], str(got))

passed = sum(1 for _, ok, _ in results if ok)
with open(os.path.join(os.path.dirname(__file__), "results.md"), "w", encoding="utf-8") as f:
    f.write(f"# Evaluation results ({passed}/{len(results)} passed)\n\nData: `{a.data_dir}` ({len(O)} unique valid recipes). Oracle = plain regex over raw JSON, independent of the bot's parser.\n\n| # | check | result |\n|---|---|---|\n")
    for i, (n_, ok, d) in enumerate(results, 1):
        f.write(f"| {i} | {n_} | {'PASS' if ok else 'FAIL ' + d} |\n")
print(f"\n{passed}/{len(results)} passed -> eval/results.md")
sys.exit(0 if passed == len(results) else 1)

"""Task 3 - evidence-based ingredient substitution.

Evidence hierarchy (reported separately, never blended):
  DIRECT    recipes whose own ingredient line offers both options ("3 eggs or 3/4 cup applesauce")
  INDIRECT  *similar* recipes (title words + ingredient overlap, Jaccard >= SIM_MIN) that do NOT contain the
            target ingredient but DO contain the candidate  -> "this kind of dish is made with X instead"
  CONFLICT  candidate mostly appears *together with* the target in similar recipes (it complements, not replaces)
Candidate substitutes come from a small role table (general culinary knowledge = PREDICTION, labelled as such);
the dataset decides how well each candidate is supported.  No evidence -> the candidate is shown as unsupported,
and an ingredient with no role entry is refused rather than guessed.
Nothing here is a medical-safety claim: restrictions are checked by text matching on ingredient lines only.
"""
import json
import math
import re
from .db import UNIQUE, row_to_recipe, get_recipe
from .normalize import parse_line, split_steps, fmt_qty, STAPLES
from .restrict import check_line, resolve_exclusion, CATS

SIM_MIN = 0.25
STOP_TITLE = {"with", "and", "the", "a", "of", "in", "easy", "best", "classic", "simple", "quick", "homemade", "style"}

# ---------------------------------------------------------------- role table (prediction layer)
def S(display, canon, mode="same", qty=None, unit=None, factor=1.0, extra=(), prep="", effect=""):
    return dict(display=display, canon=canon, mode=mode, qty=qty, unit=unit, factor=factor,
                extra=list(extra), prep=prep, effect=effect)


TABLE = {
    "egg": dict(role="binder / moisture / some leavening", family={"egg", "egg white", "egg yolk"}, cands=[
        S("unsweetened applesauce", "applesauce", "per_unit", 0.25, "cup",
          effect="moister, denser crumb, slightly less rise; mild sweetness"),
        S("mashed ripe banana", "banana", "per_unit", 0.25, "cup",
          effect="adds banana flavour and moisture; denser; browns faster"),
        S("ground flaxseed", "flaxseed", "per_unit", 1, "tablespoon",
          extra=[dict(display="water", mode="per_unit", qty=3, unit="tablespoon")],
          prep="Stir the flaxseed with the water and let it stand 5 minutes until gel-like.",
          effect="binds well, slightly nutty/earthy and denser; little lift"),
        S("plain yogurt", "yogurt", "per_unit", 0.25, "cup", effect="moist and tender; adds slight tang (contains dairy)"),
        S("silken tofu, blended", "silken tofu", "per_unit", 0.25, "cup", prep="Blend the tofu until completely smooth.",
          effect="neutral flavour, dense and moist; little lift"),
    ]),
    "milk": dict(role="liquid / richness", family={"milk"}, cands=[
        S("soy milk", "soy milk", effect="closest in protein and browning; slight bean flavour"),
        S("almond milk", "almond milk", effect="thinner, slightly nutty; less richness"),
        S("oat milk", "oat milk", effect="creamy, slightly sweet"),
        S("coconut milk", "coconut milk", effect="richer, coconut flavour"),
        S("water", "water", effect="loses richness and browning; add 1 tbsp oil per cup for fat"),
    ]),
    "cream": dict(role="fat / richness / thickening in sauces", family={"cream", "heavy cream", "half and half"}, cands=[
        S("full-fat coconut cream", "coconut cream", effect="thick and rich; mild coconut flavour"),
        S("full-fat coconut milk", "coconut milk", effect="similar richness, thinner; simmer a little longer to thicken"),
        S("raw cashews, soaked", "cashew", "scale", factor=0.5,
          extra=[dict(display="water", mode="scale_same", factor=0.5)],
          prep="Soak the cashews 30 minutes (or simmer 10), then blend with the water until silky.",
          effect="neutral, very creamy; contains tree nuts"),
        S("silken tofu, blended", "silken tofu", "scale", factor=0.75, prep="Blend until completely smooth.",
          effect="thick and neutral; less rich, can split if boiled hard"),
        S("soy milk", "soy milk", effect="thin - sauce will be less rich; thicken with a little flour or cornstarch"),
        S("evaporated milk", "evaporated milk", effect="creamy, slightly cooked-milk flavour (contains dairy)"),
    ]),
    "butter": dict(role="fat / tenderness / flavour", family={"butter"}, cands=[
        S("vegetable oil", "vegetable oil", "scale", factor=0.75, effect="moist, tender; loses butter flavour; use 3/4 the amount"),
        S("olive oil", "olive oil", "scale", factor=0.75, effect="fruity flavour; moist; use 3/4 the amount"),
        S("coconut oil", "coconut oil", "same", effect="solid like butter at room temp; slight coconut flavour"),
        S("margarine", "margarine", "same", effect="closest texture; some margarines contain milk - check the label"),
        S("unsweetened applesauce", "applesauce", "scale", factor=0.5, effect="much lower fat: softer, cakier crumb"),
    ]),
    "buttermilk": dict(role="acid / tenderness / liquid", family={"buttermilk"}, cands=[
        S("soy milk + lemon juice", "soy milk", "same",
          extra=[dict(display="lemon juice", mode="fixed", qty=1, unit="tablespoon")],
          prep="Stir the lemon juice into the soy milk and let it stand 5-10 minutes to curdle.",
          effect="similar acidity and tenderness; soy flavour"),
    ]),
    "sour cream": dict(role="acid / richness / moisture", family={"sour cream"}, cands=[
        S("plain yogurt", "yogurt", effect="very close; slightly thinner (contains dairy)"),
        S("silken tofu, blended", "silken tofu", "same",
          extra=[dict(display="lemon juice", mode="fixed", qty=1, unit="teaspoon")], prep="Blend until smooth.",
          effect="neutral, thick; tang comes only from the lemon"),
    ]),
    "cheese": dict(role="salty / savoury flavour, melt", family={"cheese", "parmesan", "mozzarella", "cheddar", "feta", "ricotta", "cream cheese"}, cands=[
        S("nutritional yeast", "nutritional yeast", "scale", factor=0.25,
          effect="gives savoury, cheesy flavour but does NOT melt or stretch"),
    ]),
    "flour": dict(role="structure / bulk (wheat gluten)", family={"flour", "whole wheat flour", "bread flour"}, cands=[
        S("rice flour", "rice flour", effect="gluten-free but gritty/crumbly; yeast breads will not rise like wheat"),
        S("almond flour", "almond flour", effect="moist, dense, nutty; contains tree nuts; needs extra binder"),
        S("cornstarch", "cornstarch", "scale", factor=0.5, effect="works for thickening only, not for structure"),
    ]),
    "sugar": dict(role="sweetness / moisture / browning", family={"sugar"}, cands=[
        S("honey", "honey", "scale", factor=0.75, effect="moister, browns faster; reduce other liquid slightly (not vegan)"),
        S("maple syrup", "maple syrup", "scale", factor=0.75, effect="moister, maple flavour; reduce other liquid slightly"),
        S("brown sugar", "brown sugar", effect="more molasses flavour and moisture"),
    ]),
    "peanut butter": dict(role="fat / binding / flavour", family={"peanut butter"}, cands=[
        S("almond or sunflower-seed butter", "nut butter", effect="similar texture; flavour differs (almond is a tree nut)"),
        S("tahini", "tahini", effect="sesame flavour, more bitter; similar fat and binding"),
    ]),
}
TABLE_KEY = {"heavy cream": "cream", "half and half": "cream", "whipping cream": "cream", "parmesan": "cheese",
             "mozzarella": "cheese", "cheddar": "cheese", "feta": "cheese", "ricotta": "cheese",
             "cream cheese": "cheese", "whole wheat flour": "flour", "bread flour": "flour"}


# ---------------------------------------------------------------- helpers
def _prim(rec):
    return {e["opts"][0] for e in rec["parsed"] if not e.get("o")}


def _chunks(xs, n=900):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _rows(con, ids):
    for ch in _chunks(list(ids)):
        for r in con.execute(f"SELECT r.* FROM recipes r WHERE {UNIQUE} AND r.id IN ({','.join('?'*len(ch))})", ch):
            yield row_to_recipe(r)


def similar_pool(con, rec, target_family):
    """Similar recipes by (a) title words, (b) overlap of the recipe's own ingredients."""
    core = {c for c in _prim(rec) if c not in STAPLES and c not in target_family}
    ids = set()
    toks = [t for t in re.findall(r"[a-z]+", rec["title"].lower()) if t not in STOP_TITLE and len(t) > 2]
    if toks:
        q = " OR ".join(f'"{t}"' for t in toks)
        ids |= {r[0] for r in con.execute(
            "SELECT r.id FROM recipes_fts JOIN recipes r ON r.rowid=recipes_fts.rowid WHERE recipes_fts MATCH ? "
            "ORDER BY bm25(recipes_fts, 6.0, 1.0) LIMIT 600", (f"title : ({q})",))}
    if len(core) >= 3:
        need = max(3, math.ceil(len(core) / 2))
        ids |= {r[0] for r in con.execute(
            f"SELECT recipe_id FROM recipe_ingredients WHERE is_alt=0 AND canon IN ({','.join('?'*len(core))}) "
            f"GROUP BY recipe_id HAVING COUNT(DISTINCT canon)>=? ORDER BY COUNT(DISTINCT canon) DESC LIMIT 800",
            (*core, need))}
    ids.discard(rec["id"])
    out = []
    for r in _rows(con, ids):
        p = _prim(r)
        pc = {c for c in p if c not in STAPLES and c not in target_family}
        sim = len(core & pc) / len(core | pc) if (core | pc) else 0
        if sim >= SIM_MIN:
            out.append((r, p, sim))
    return out


def direct_evidence(con, family, cand):
    ph = ",".join("?" * len(family))
    q = (f"SELECT DISTINCT a.recipe_id FROM recipe_ingredients a JOIN recipe_ingredients b "
         f"ON a.recipe_id=b.recipe_id AND a.line_idx=b.line_idx JOIN recipes r ON r.id=a.recipe_id "
         f"WHERE a.canon IN ({ph}) AND b.canon=? AND a.canon<>b.canon AND a.is_alt+b.is_alt=1 AND {UNIQUE} ORDER BY a.recipe_id")
    return [r[0] for r in con.execute(q, (*family, cand))]


def presence(con, cand):
    return con.execute("SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredients ri JOIN recipes r ON r.id=ri.recipe_id "
                       f"WHERE ri.canon=? AND ri.is_alt=0 AND {UNIQUE}", (cand,)).fetchone()[0]


def strength(direct, support):
    if direct >= 5 or support >= 8:
        return "strong"
    if direct >= 2 or support >= 3:
        return "moderate"
    if direct >= 1 or support >= 1:
        return "weak"
    return "none"


RANK = {"strong": 3, "moderate": 2, "weak": 1, "none": 0}


def violates(spec, exclusions, target):
    """Does the candidate (display text + extras) break a hard restriction?  -> reason or None"""
    texts = [spec["display"]] + [x["display"] for x in spec["extra"]]
    for ex in exclusions:
        for t in texts:
            if ex.kind == "cat":
                st, m = check_line(t, ex.key)
                if st == "violates":
                    return f"{ex.label}: '{m}' in '{t}'"
            elif spec["canon"] == ex.key:
                return f"{ex.label}"
    return None


def _amount(line_entry, spec):
    q, unit = line_entry.get("q"), line_entry.get("unit") or ""
    mode = spec["mode"]
    if q is None:
        return None
    if line_entry.get("dim") in ("vol", "wt"):   # parse_line stores base units (ml/g) for these
        return None
    if mode == "per_unit":
        return f"{fmt_qty(q * spec['qty'])} {spec['unit']}{'s' if q * spec['qty'] > 1 and spec['unit'] in ('cup', 'tablespoon') else ''}"
    return None


def _new_line(raw, entry, spec):
    """Rebuild the ingredient line for the substitute, keeping the original quantity where it is meaningful."""
    m = re.match(r"^\s*([\d¼½¾⅓⅔⅛][\d\s/.¼½¾⅓⅔⅛\-–]*)?\s*(.*)$", raw)
    qty_txt, rest = (m.group(1) or "").strip(), m.group(2)
    mode = spec["mode"]
    if mode == "per_unit" and entry.get("q") is not None and entry.get("dim") == "cnt" and not entry.get("unit"):
        amt = f"{fmt_qty(entry['q'] * spec['qty'])} {spec['unit']}" + ("s" if entry["q"] * spec["qty"] > 1 else "")
        lines = [f"{amt} {spec['display']}"]
        for x in spec["extra"]:
            lines.append(f"{fmt_qty(entry['q'] * x['qty'])} {x['unit']}{'s' if entry['q'] * x['qty'] > 1 else ''} {x['display']}")
        return lines, True
    unit_txt = re.match(r"^(cups?|tablespoons?|tbsps?|teaspoons?|tsps?|ounces?|oz|pounds?|lbs?|grams?|g|ml|pints?|quarts?)\b\s*(?:of\s+)?", rest, re.I)
    unit_part = unit_txt.group(0).strip() if unit_txt else ""
    if mode in ("same", "scale") and qty_txt and unit_part:
        base = entry.get("q")  # base units; scale numerically using the written quantity instead
        try:
            val = sum(float(x.split("/")[0]) / float(x.split("/")[1]) if "/" in x else float(x) for x in qty_txt.replace("–", "-").split("-")[0].split())
        except ValueError:
            val = None
        if val is not None:
            f = spec["factor"] if mode == "scale" else 1.0
            lines = [f"{fmt_qty(val * f)} {unit_part} {spec['display']}"]
            for x in spec["extra"]:
                if x["mode"] == "fixed":
                    lines.append(f"{x['qty']} {x['unit']} {x['display']}")
                elif x["mode"] == "scale_same":
                    lines.append(f"{fmt_qty(val * x['factor'])} {unit_part} {x['display']}")
            return lines, True
    # fallback: no reliable quantity arithmetic
    lines = [f"{spec['display']}  (amount: replace the original '{raw.strip()}' like-for-like, then adjust to taste - quantity NOT verified)"]
    for x in spec["extra"]:
        if x["mode"] == "fixed":
            lines.append(f"{x['qty']} {x['unit']} {x['display']}")
    return lines, False


def _term_rx(canons):
    words = []
    for c in canons:
        words.append(re.escape(c).replace(r"\ ", r"\s+") + r"s?")
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I)


def _clean_display_line(line):
    return re.sub(r"\s+", " ", re.sub(r"\bADVERTISEMENT\b", "", line, flags=re.I)).strip()


# ---------------------------------------------------------------- main entry
def adapt(con, recipe_id, target, exclusions=(), dataset_only=True, choose=None):
    """target = canonical ingredient name ('egg', 'cream' ...). Returns a result dict (see format_adaptation)."""
    rec = get_recipe(con, recipe_id)
    if not rec:
        return {"error": f"Recipe {recipe_id} not found."}
    key = TABLE_KEY.get(target, target)
    fam0 = set(TABLE.get(key, {}).get("family", set())) | {target}
    fam_from_line = {c for e in rec["parsed"] for c in e["opts"] if c in fam0}
    if not fam_from_line:
        return {"error": f"'{target}' is not an ingredient of [{recipe_id}] {rec['title']} (checked all ingredient lines).",
                "recipe": rec}
    entry = TABLE.get(key)
    if not entry:
        return {"refused": True, "recipe": rec, "target": target,
                "msg": (f"I have no role knowledge for '{target}' and cannot infer one safely from the dataset alone, so I will not "
                        f"invent a substitute. Supported targets: {', '.join(sorted(TABLE))}. You can still delete the ingredient "
                        f"yourself, but the effect would be unverified.")}
    family = set(entry["family"]) | {target}
    ex_all = list(exclusions)
    t_ex = resolve_exclusion(target)
    if t_ex and t_ex not in ex_all:
        ex_all.append(t_ex)
    pool = similar_pool(con, rec, family)
    E = [(r, p, s) for r, p, s in pool if not (p & family)]
    P = [(r, p, s) for r, p, s in pool if p & family]
    own = _prim(rec)
    cands, rejected = [], []
    for i, spec in enumerate(entry["cands"]):
        why = violates(spec, ex_all, target)
        pres = presence(con, spec["canon"])
        if why:
            rejected.append((spec["display"], "violates your restriction - " + why))
            continue
        if dataset_only and pres == 0:
            rejected.append((spec["display"], "does not appear as an ingredient anywhere in the dataset (you asked for dataset-only)"))
            continue
        sup = [(r["id"], s) for r, p, s in E if spec["canon"] in p]
        sup.sort(key=lambda x: -x[1])
        withT = sum(1 for r, p, s in P if spec["canon"] in p)
        direct = direct_evidence(con, family, spec["canon"])
        st = strength(len(direct), len(sup))
        conflict = withT >= 3 and withT / (withT + len(sup)) >= 0.75
        cands.append(dict(spec=spec, order=i, direct=direct, support=sup, with_target=withT, presence=pres,
                          strength=st, conflict=conflict, already=spec["canon"] in own))
    cands.sort(key=lambda c: (-RANK[c["strength"]], -len(c["direct"]), -len(c["support"]),
                              c["conflict"], c["already"], c["order"]))
    res = {"recipe": rec, "target": target, "role": entry["role"], "cands": cands, "rejected": rejected,
           "n_similar": len(pool), "n_without": len(E), "n_with": len(P), "exclusions": ex_all,
           "user_exclusions": list(exclusions), "dataset_only": dataset_only}
    if not cands:
        res["refused"] = True
        res["msg"] = "No candidate substitute satisfies your restrictions" + (" and exists in the dataset." if dataset_only else ".")
        return res
    pick = cands[0]
    if choose:
        m = [c for c in cands if choose.lower() in c["spec"]["display"].lower() or choose.lower() == c["spec"]["canon"]]
        if m:
            pick = m[0]
    res["pick"] = pick
    _rewrite(res, family)
    return res


def _rewrite(res, family):
    rec, spec = res["recipe"], res["pick"]["spec"]
    parsed_by_line = {}
    for e in rec["parsed"]:
        parsed_by_line.setdefault(e["i"], []).append(e)
    new, changes, line_details = [], [], []
    for i, raw in enumerate(rec["lines"]):
        ents = [e for e in parsed_by_line.get(i, []) if set(e["opts"]) & family]
        if not ents:
            line = _clean_display_line(raw)
            new.append(line)
            line_details.append({"text": line, "source": None, "exact": True, "note": ""})
            continue
        e = ents[0]
        kept = None
        if re.search(r"\bor\b", raw, re.I):               # the line already names an alternative
            for part in re.split(r"\s+or\s+", raw, flags=re.I):
                pe = parse_line(part)
                if pe and not (set(pe[0]["opts"]) & family):
                    kept = part.strip()
                    break
        if kept:
            kept = _clean_display_line(kept)
            source = _clean_display_line(raw)
            new.append(kept)
            changes.append((source, [kept], True, "kept the alternative already written on that line"))
            line_details.append({"text": kept, "source": source, "exact": True,
                                 "note": "kept the alternative already written on that line"})
            continue
        lines, exact = _new_line(raw, e, spec)
        lines = [_clean_display_line(line) for line in lines]
        source = _clean_display_line(raw)
        new.extend(lines)
        note = "amount calculated from the original quantity; recipe outcome not verified" if exact else "quantity not verified"
        changes.append((source, lines, exact, note))
        line_details.extend({"text": line, "source": source, "exact": exact, "note": note} for line in lines)
    rx = _term_rx(family | {res["target"]})
    short = re.split(r"\s*(?:\+|\(|,)", spec["display"])[0].strip()
    steps, flagged = [], []
    for s in split_steps(rec["instructions"]):
        if rx.search(s):
            steps.append(rx.sub(short, s))
            flagged.append(len(steps))
        else:
            steps.append(s)
    if spec["prep"]:
        steps.insert(0, "Prepare the substitute: " + spec["prep"])
        flagged = [f + 1 for f in flagged]
    res.update(new_lines=new, changes=changes, line_details=line_details, new_steps=steps, flagged=flagged)
    # re-audit the result against the user's restrictions (other lines may still conflict)
    left = []
    for ex in res["exclusions"]:
        if ex.kind != "cat":
            continue
        for ln in new:
            st, m = check_line(ln, ex.key)
            if st == "violates":
                left.append((ex.label, ln, m))
    res["still_violating"] = left


def format_adaptation(res):
    if res.get("error"):
        return res["error"]
    rec = res["recipe"]
    if res.get("refused"):
        extra = ""
        if res.get("rejected"):
            extra = "\n\n### Candidates not used\n" + "\n".join(f"- **{n}:** {w}" for n, w in res["rejected"])
        return (f"## Recipe adaptation\n\n**Recipe:** {rec['title']} (`{rec['id']}`)\n\n"
                f"**Result:** No reliable change proposed.\n\n{res['msg']}{extra}")
    pk, spec = res["pick"], res["pick"]["spec"]
    target = res["target"]
    target_exclusion = resolve_exclusion(target)
    other_exclusions = [ex for ex in res.get("user_exclusions", res["exclusions"]) if ex != target_exclusion]

    L = [
        "## Recipe adaptation",
        "",
        f"**Recipe:** {rec['title']} (`{rec['id']}`)",
        "",
        "## Request and constraints",
        "",
        f"- **Remove:** `{target}`.",
        f"- **Dataset requirement:** {'All proposed substitutes must appear in the dataset.' if res['dataset_only'] else 'Dataset-only substitutes were not requested.'}",
        "- **Additional hard restrictions:** " + ("; ".join(str(ex) for ex in other_exclusions) or "None stated."),
        "",
        "## Local evidence",
        "",
        f"The search found **{res['n_similar']} similar recipes** using title/ingredient overlap "
        f"(Jaccard threshold ≥ {SIM_MIN:g}). **{res['n_without']}** do not contain `{target}`; "
        f"**{res['n_with']}** do.",
        "",
        "*Similarity is a retrieval signal, not proof that every result is a baked recipe or that an ingredient "
        "caused a successful substitution. Evidence below is indirect unless marked DIRECT.*",
        "",
        "## Candidate replacements",
        "",
    ]
    for i, c in enumerate(res["cands"], 1):
        s = c["spec"]
        evidence_type = "Direct evidence" if c["direct"] else (
            "Indirect evidence" if c["support"] else "No similar-recipe evidence")
        L.append(f"### {i}. {s['display']} — {c['strength'].capitalize()} support ({evidence_type})")
        L.append(f"- **Similar recipes without `{target}` using this candidate:** {len(c['support'])}.")
        if c["direct"]:
            L.append("- **Direct evidence IDs:** " + ", ".join(f"`{rid}`" for rid in c["direct"][:4]) + ".")
        if c["support"]:
            L.append("- **Indirect evidence IDs:** " + ", ".join(f"`{rid}`" for rid, _ in c["support"][:4]) + ".")
        if not c["support"] and not c["direct"]:
            L.append("- No direct or indirect evidence for this candidate was found in the similar-recipe set.")
        if c["with_target"]:
            L.append(f"- **Co-occurrence caveat:** {c['with_target']} similar recipes contain both `{target}` "
                     "and this candidate; co-occurrence does not establish replacement.")
        if c["already"]:
            L.append("- **Already in this recipe:** yes; choosing it adds more, rather than replacing the existing amount.")
        L.append(f"- **Found anywhere in dataset:** {c['presence']:,} recipes. "
                 "This dataset-wide count is not substitution evidence.")
        L.append(f"- **Expected effect (prediction):** {s['effect'] or 'not specified'}.")
        L.append("")

    L.extend([
        "## Recommendation",
        "",
        f"**Selected:** {spec['display']} — {pk['strength']} local support.",
    ])
    if pk["support"]:
        L.append(f"This is used in {len(pk['support'])} similar recipes that omit `{target}` "
                 "(examples listed above).")
    elif pk["direct"]:
        L.append(f"Direct alternatives are present in {len(pk['direct'])} recipe line(s) (IDs listed above).")
    else:
        L.append("No direct or similar-recipe evidence supports this selection; it is based on the role prediction only.")
    if pk["conflict"]:
        L.append(f"**Caveat:** the candidate also appears alongside `{target}` in {pk['with_target']} similar recipes.")
    if pk["already"]:
        L.append("The ingredient already appears in the original recipe, so this adds more of it.")
    if res["rejected"]:
        L.extend(["", "## Candidates excluded by constraints", ""])
        L.extend(f"- **{name}:** {reason}." for name, reason in res["rejected"])

    L.extend(["", "## Updated ingredient list", ""])
    for detail in res.get("line_details", []):
        line = f"- {detail['text']}"
        if detail["source"]:
            line += f" — **replaces:** {detail['source']}"
            if not detail["exact"]:
                line += " *(quantity not verified)*"
        L.append(line)

    L.extend([
        "",
        "## Revised instructions",
        "",
        "*Automatic wording edits only. Review every step marked **[REVIEW]** before cooking.*",
    ])
    L.extend(f"{i}. {step}" + (" **[REVIEW]**" if i in res["flagged"] else "")
             for i, step in enumerate(res["new_steps"], 1))
    L.extend([
        "",
        "## Expected result",
        "",
        f"**Prediction, not a verified outcome:** {spec['effect'] or 'The effect is uncertain.'}",
    ])
    if res["still_violating"]:
        L.extend(["", "## Restriction check", "",
                  "**Potential conflicts remain:** " +
                  "; ".join(f"{lab}: `{ln}`" for lab, ln, _ in res["still_violating"]) +
                  ". Consider adapting those ingredients too."])
    else:
        L.extend(["", "## Restriction and source notes", "",
                  "No remaining text-matched conflicts were found for the checked restrictions. "
                  "Ingredient-text checks are not an allergy-safety guarantee; check product labels.",
                  "No external web sources were used."])
    return "\n".join(L)

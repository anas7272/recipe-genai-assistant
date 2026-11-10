"""Programmatic statistics over the COMPLETE filtered set (no LLM arithmetic)."""
import statistics
from dataclasses import dataclass, field
from .db import UNIQUE, totals, clean_ingredients, row_to_recipe
from .restrict import audit

STEP_RULE = ("steps = non-empty lines of the instructions field (if a recipe is a single paragraph: its sentences). "
             "Ingredient count = ingredient lines after removing 'ADVERTISEMENT', blanks, headings and equipment lines.")
NORM_NOTE = ("Ingredient names are normalised by whole-word matching + a synonym lexicon (e.g. 'Parmigiano-Reggiano' -> parmesan, "
             "'2 large eggs, beaten' -> egg). 'egg' does not match eggplant/Reggiano; different products stay different "
             "(tomato vs tomato paste). A recipe 'contains' X if X is a primary ingredient on any line (alternatives after 'or' are not counted).")


@dataclass
class Spec:
    include_all: list = field(default_factory=list)
    include_any: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    title: list = field(default_factory=list)

    def describe(self):
        p = []
        if self.include_all:
            p.append("contains ALL of: " + ", ".join(self.include_all))
        if self.include_any:
            p.append("contains ANY of: " + ", ".join(self.include_any))
        if self.title:
            p.append("title matches: " + " ".join(self.title))
        p += [str(e) for e in self.exclude]
        return "; ".join(p) or "no filter (whole dataset)"


def filtered(con, spec):
    sql, args = f"SELECT r.id,r.title,r.n_steps,r.n_ingredients,r.ingredients,r.parsed FROM recipes r WHERE {UNIQUE}", []
    for c in spec.include_all:
        sql += " AND r.id IN (SELECT recipe_id FROM recipe_ingredients WHERE canon=? AND is_alt=0)"
        args.append(c)
    if spec.include_any:
        sql += " AND r.id IN (SELECT recipe_id FROM recipe_ingredients WHERE is_alt=0 AND canon IN (%s))" % ",".join("?" * len(spec.include_any))
        args += spec.include_any
    if spec.title:
        import re
        q = " AND ".join('"%s"' % re.sub(r"[^a-z0-9]", "", t.lower()) for t in spec.title)
        sql += " AND r.rowid IN (SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ?)"
        args.append(f"title : ({q})")
    rows = []
    for r in con.execute(sql + " ORDER BY r.id", args):
        if spec.exclude:
            lines = clean_ingredients(r["ingredients"])
            import json
            if audit(lines, json.loads(r["parsed"]), spec.exclude)["violations"]:
                continue
        rows.append(r)
    return rows


def _head(con, spec, rows):
    t = totals(con)
    return (f"Filter: {spec.describe()}\nRecipes analysed: {len(rows):,} "
            f"(denominator = {t['unique_valid']:,} unique valid recipes; raw={t['raw']:,}, invalid={t['raw']-t['valid']:,}, "
            f"duplicates removed={t['duplicates']:,})")


def count(con, spec):
    rows = filtered(con, spec)
    t = totals(con)["unique_valid"]
    pct = 100 * len(rows) / t if t else 0
    return (f"{_head(con, spec, rows)}\nCalculation: count = {len(rows):,}; percentage = {len(rows):,} / {t:,} x 100 = {pct:.2f}%\n"
            f"Normalisation: {NORM_NOTE}")


def ing_count_stats(con, spec):
    rows = filtered(con, spec)
    xs = [r["n_ingredients"] for r in rows]
    if not xs:
        return _head(con, spec, rows) + "\nNo recipes match, so no statistics."
    return (f"{_head(con, spec, rows)}\nIngredient lines per recipe: mean = sum/n = {sum(xs)}/{len(xs)} = {statistics.mean(xs):.2f}; "
            f"median = {statistics.median(xs)}; min = {min(xs)}; max = {max(xs)}\n{STEP_RULE}")


def step_stats(con, spec):
    rows = filtered(con, spec)
    xs = [r["n_steps"] for r in rows]
    if not xs:
        return _head(con, spec, rows) + "\nNo recipes match."
    return f"{_head(con, spec, rows)}\nSteps per recipe: mean = {statistics.mean(xs):.2f}; median = {statistics.median(xs)}; min = {min(xs)}; max = {max(xs)}\n{STEP_RULE}"


def common_ingredients(con, spec, top=15, skip_staples=False):
    rows = filtered(con, spec)
    if not rows:
        return _head(con, spec, rows) + "\nNo recipes match."
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _f(id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM _f")
    con.executemany("INSERT INTO _f VALUES(?)", [(r["id"],) for r in rows])
    skip = {"salt", "water", "black pepper"} if skip_staples else set()
    q = ("SELECT canon, COUNT(DISTINCT recipe_id) n FROM recipe_ingredients WHERE is_alt=0 AND recipe_id IN (SELECT id FROM _f) "
         "GROUP BY canon ORDER BY n DESC, canon LIMIT ?")
    res = [(c, n) for c, n in con.execute(q, (top + len(skip) + len(spec.include_all),)) if c not in skip][:top]
    lines = [f"  {i}. {c}: {n:,} recipes ({100*n/len(rows):.1f}%)" for i, (c, n) in enumerate(res, 1)]
    return (f"{_head(con, spec, rows)}\nMost common ingredients (recipes containing it / {len(rows):,}"
            f"{', staples salt/water/pepper excluded' if skip_staples else ''}):\n" + "\n".join(lines) + f"\nNormalisation: {NORM_NOTE}")


def rank_steps(con, spec, n=5, fewest=True):
    rows = [r for r in filtered(con, spec) if r["n_steps"] > 0]
    rows.sort(key=lambda r: (r["n_steps"] if fewest else -r["n_steps"], r["id"]))
    lines = [f"  {i}. [{r['id']}] {r['title']} - {r['n_steps']} steps" for i, r in enumerate(rows[:n], 1)]
    return (f"{_head(con, spec, rows)}\nRanking: {'fewest' if fewest else 'most'} instruction steps, ties broken by recipe ID "
            f"(ascending). {STEP_RULE}\n" + ("\n".join(lines) if lines else "  no matching recipes"))

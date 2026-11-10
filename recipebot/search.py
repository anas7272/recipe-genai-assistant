"""Recipe search: FTS5/BM25 retrieval over titles+ingredients, then exact structured filtering.

Why not only embeddings?  Constraints (dairy-free, includes garlic, <= N steps) must be exact, so
retrieval proposes candidates (BM25, porter-stemmed) and a deterministic filter decides eligibility
on the *complete* candidate set (cap = 20,000 title matches, reported if hit).
"""
import re
from dataclasses import dataclass, field
from .db import UNIQUE, row_to_recipe
from .restrict import audit

CAP = 20000
SOFT = {"pasta", "dish", "dishes", "recipe", "recipes", "meal", "food"}


@dataclass
class Filters:
    dish: list = field(default_factory=list)       # title words, e.g. ["penne", "pasta"]
    include: list = field(default_factory=list)    # canonical ingredients that must be present
    exclude: list = field(default_factory=list)    # Exclusion objects (hard)
    max_steps: int = None

    def describe(self):
        parts = []
        if self.dish:
            parts.append("title/text matches '" + " ".join(self.dish) + "'")
        if self.include:
            parts.append("contains " + " + ".join(self.include))
        parts += [str(e) for e in self.exclude]
        if self.max_steps:
            parts.append(f"<= {self.max_steps} steps")
        return "; ".join(parts) or "(none)"


def _tok(ts):
    return [re.sub(r"[^a-z0-9]", "", t.lower()) for t in ts if re.sub(r"[^a-z0-9]", "", t.lower())]


def _title_has(title, toks):
    low = title.lower()
    for t in toks:
        alts = [t, t + "s", t + "es"] + ([t[:-1] + "ies"] if t.endswith("y") else [])
        if not any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", low) for a in alts):
            return False
    return True


def candidate_rows(con, f):
    """-> (rows, how)"""
    if f.dish:
        hard = [t for t in f.dish if t.lower() not in SOFT]
        toks = _tok(hard or f.dish)   # generic words like 'pasta'/'dish' are dropped when a specific dish word exists
        q = " AND ".join(f'"{t}"' for t in toks)
        sql = ("SELECT r.* FROM recipes_fts JOIN recipes r ON r.rowid=recipes_fts.rowid "
               "WHERE recipes_fts MATCH ? ORDER BY bm25(recipes_fts, 6.0, 1.0) LIMIT ?")
        rows = con.execute(sql, (f"title : ({q})", CAP)).fetchall()
        rows = [r for r in rows if _title_has(r["title"], toks)]   # porter stemming also matches 'penn' for 'penne'; require the real word
        if rows:
            return rows, "title"
        rows = con.execute(sql, (q, CAP)).fetchall()
        return rows, "title+ingredients"
    if f.include:
        sub = " INTERSECT ".join("SELECT recipe_id FROM recipe_ingredients WHERE canon=? AND is_alt=0" for _ in f.include)
        rows = con.execute(f"SELECT r.* FROM recipes r WHERE {UNIQUE} AND r.id IN ({sub}) "
                           "ORDER BY r.n_steps, r.id LIMIT ?", (*f.include, CAP)).fetchall()
        return rows, "ingredients"
    return [], "none"


def search(con, f, limit=5):
    rows, how = candidate_rows(con, f)
    out, n_text = [], len(rows)
    for r in rows:
        rec = row_to_recipe(r)
        have = {c for e in rec["parsed"] for c in e["opts"][:1]}
        if any(i not in have for i in f.include):
            continue
        if f.max_steps and rec["n_steps"] > f.max_steps:
            continue
        a = audit(rec["lines"], rec["parsed"], f.exclude)
        if a["violations"]:
            continue
        rec["audit"] = a
        rec["evidence"] = [rec["lines"][e["i"]] for e in rec["parsed"] if e["opts"][0] in f.include]
        out.append(rec)
    return {"results": out[:limit], "total": len(out), "candidates": n_text, "how": how,
            "capped": n_text >= CAP, "all_ids": [x["id"] for x in out]}


def format_recipe(rec, f=None, full=False):
    L = [f"[{rec['id']}] {rec['title']}  ({rec['n_steps']} steps, {len(rec['lines'])} ingredient lines)"]
    if f and rec.get("evidence"):
        L.append("   matches: " + "; ".join(dict.fromkeys(rec["evidence"])))
    a = rec.get("audit")
    if a:
        for lab, ln, t in a["exceptions"]:
            L.append(f"   {lab}: kept - '{ln}' contains '{t}', which is a non-dairy/allowed form")
        for lab, ln, t in a["cautions"]:
            L.append(f"   CAUTION ({lab}): '{ln}' may contain it - check the label")
    if f and f.exclude and not (a and (a["cautions"] or a["exceptions"])):
        L.append("   restriction check: none of the %d ingredient lines matched (%s)" % (len(rec["lines"]), ", ".join(str(e) for e in f.exclude)))
    if full:
        L.append("   Ingredients:")
        L += [f"     - {x}" for x in rec["lines"]]
        L.append("   Instructions:")
        from .normalize import split_steps
        L += [f"     {i}. {s}" for i, s in enumerate(split_steps(rec["instructions"]), 1)]
    return "\n".join(L)

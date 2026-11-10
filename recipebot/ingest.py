"""Build data/recipes.db from the three Recipe Box JSON files.

python -m recipebot.ingest --data-dir data --db data/recipes.db

Stable ID = "<source>-<original key>", e.g. "epi-3f2a..." (source in ar | epi | fn).
Original title / ingredient list / instructions are stored untouched (columns title, ingredients, instructions).
Derived columns: parsed (normalised ingredient entries), n_steps, n_ingredients, is_valid, dup_of.
"""
import argparse, json, os, sqlite3, sys, time
from .normalize import parse_line, split_steps
from .db import clean_ingredients

SOURCES = {"ar": "recipes_raw_nosource_ar.json", "epi": "recipes_raw_nosource_epi.json", "fn": "recipes_raw_nosource_fn.json"}

SCHEMA = """
DROP TABLE IF EXISTS recipes; DROP TABLE IF EXISTS recipe_ingredients; DROP TABLE IF EXISTS recipes_fts;
CREATE TABLE recipes(
  id TEXT PRIMARY KEY, source TEXT, source_key TEXT,
  title TEXT, ingredients TEXT, instructions TEXT, picture_link TEXT,
  n_steps INT, n_ingredients INT, is_valid INT, dup_of TEXT, parsed TEXT);
CREATE TABLE recipe_ingredients(recipe_id TEXT, line_idx INT, canon TEXT, is_alt INT);
CREATE VIRTUAL TABLE recipes_fts USING fts5(title, ing, tokenize='porter unicode61');
"""


def build(data_dir, db_path, sources=SOURCES, quiet=False):
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    seen, counts = {}, {"raw": 0, "invalid": 0, "dup": 0}
    t0 = time.time()
    for src, fname in sources.items():
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            sys.exit(f"Missing {path}. Download the three JSON files from https://eightportions.com/datasets/Recipes/ into {data_dir}/")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key, r in data.items():
            counts["raw"] += 1
            rid = f"{src}-{key}"
            title = (r.get("title") or "").strip() if isinstance(r, dict) else ""
            ings_raw = (r.get("ingredients") if isinstance(r, dict) else None) or []
            instr = (r.get("instructions") if isinstance(r, dict) else None) or ""
            lines = clean_ingredients(json.dumps(ings_raw))
            steps = split_steps(instr)
            valid = int(bool(title and lines and steps))
            dup = None
            parsed = []
            if valid:
                parsed = []
                for i, ln in enumerate(lines):
                    for e in parse_line(ln):
                        e["i"] = i
                        parsed.append(e)
                sig = (title.lower(), tuple(sorted(l.lower() for l in lines)))
                if sig in seen:
                    dup = seen[sig]
                    counts["dup"] += 1
                else:
                    seen[sig] = rid
            else:
                counts["invalid"] += 1
            cur = con.execute(
                "INSERT INTO recipes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, src, key, title, json.dumps(ings_raw, ensure_ascii=False), instr, r.get("picture_link") if isinstance(r, dict) else None,
                 len(steps), len({e["i"] for e in parsed}) if parsed else len(lines), valid, dup, json.dumps(parsed, ensure_ascii=False)))
            if valid and not dup:
                con.execute("INSERT INTO recipes_fts(rowid,title,ing) VALUES(?,?,?)", (cur.lastrowid, title, " ; ".join(lines)))
                con.executemany("INSERT INTO recipe_ingredients VALUES(?,?,?,?)",
                                [(rid, e["i"], c, int(j > 0)) for e in parsed for j, c in enumerate(e["opts"])])
        del data
        if not quiet:
            print(f"  {src}: done ({counts['raw']} recipes so far, {time.time()-t0:.0f}s)")
    con.execute("CREATE INDEX ri_canon ON recipe_ingredients(canon, is_alt)")
    con.execute("CREATE INDEX ri_recipe ON recipe_ingredients(recipe_id)")
    con.execute("CREATE INDEX r_valid ON recipes(is_valid, dup_of)")
    con.commit()
    con.close()
    if not quiet:
        print(f"raw={counts['raw']} invalid={counts['invalid']} duplicates={counts['dup']} "
              f"unique_valid={counts['raw']-counts['invalid']-counts['dup']}")
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--db", default="data/recipes.db")
    a = ap.parse_args()
    build(a.data_dir, a.db)

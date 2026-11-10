"""SQLite access helpers."""
import json
import sqlite3

UNIQUE = "r.is_valid=1 AND r.dup_of IS NULL"


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def clean_ingredients(raw_json):
    """Original ingredient list minus scraper junk ('ADVERTISEMENT', blanks)."""
    return [x.strip() for x in json.loads(raw_json) if isinstance(x, str) and x.strip() and x.strip().upper() != "ADVERTISEMENT"]


def row_to_recipe(row):
    d = dict(row)
    d["lines"] = clean_ingredients(d["ingredients"])
    d["parsed"] = json.loads(d["parsed"]) if d.get("parsed") else []
    return d


def get_recipe(con, rid):
    r = con.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
    return row_to_recipe(r) if r else None


def totals(con):
    q = lambda w: con.execute(f"SELECT COUNT(*) FROM recipes r WHERE {w}").fetchone()[0]
    return {"raw": q("1=1"), "valid": q("r.is_valid=1"), "duplicates": q("r.dup_of IS NOT NULL"), "unique_valid": q(UNIQUE)}

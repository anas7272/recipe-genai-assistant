"""Conversational layer: routes each message to search / stats / matching / substitution and keeps session state.

python -m recipebot.chat --db data/recipes.db            (interactive)
python -m recipebot.chat --db data/recipes.db --script eval/demo_conversations.txt
"""
import argparse
import os
import re
import sys
from dataclasses import dataclass, field

from . import analytics, compose, db, llm, match as matcher, nlu, planner, search, substitute
import json
from .normalize import split_steps, parse_line
from .db import UNIQUE
from .restrict import resolve_exclusion, audit

HELP = """I can:
  - search:      "Find a penne pasta recipe"  then refine: "I cannot have dairy", "at most 5 steps", "more"
  - show:        "show the ingredients and instructions of #2"  (or a recipe ID)
  - statistics:  "How many recipes contain both garlic and onion?", "average number of ingredients in recipes containing tomato",
                 "What percentage of recipes contain chicken?", "most common ingredients in recipes with chicken",
                 "Among recipes containing tomato, which five have the fewest steps?"
  - match:       "I have eggs, onions, tomatoes and rice. Suggest five recipes, no peanuts, at most six steps"  then "Exclude eggs too"
  - substitute:  "Take the banana bread recipe and remove eggs"  /  "Replace cream in this pasta recipe without dairy"
Say "reset" to clear all restrictions."""


@dataclass
class Session:
    mode: str = None                   # "search" | "match"
    filters: search.Filters = field(default_factory=search.Filters)
    exclude: list = field(default_factory=list)       # persistent hard restrictions (Exclusion objects)
    offset: int = 0
    results: list = field(default_factory=list)       # ids last shown (for "#2")
    focus: str = None                  # recipe the user is most likely talking about
    have: list = field(default_factory=list)          # parsed "I have" entries
    max_steps: int = None
    top: int = 5
    prefer: str = "balanced"
    last_adapt: dict = None
    names: list = field(default_factory=list)         # (id,title) of the last name listing
    names_offset: int = 0
    history: list = field(default_factory=list)      # recent user turns; persistent constraints live above


class Bot:
    def __init__(self, db_path, use_llm=True):
        if not os.path.exists(db_path):
            sys.exit(f"Database {db_path} not found. Build it first:  python -m recipebot.ingest --data-dir data --db {db_path}")
        self.con = db.connect(db_path)
        self.s = Session()
        self.use_llm = use_llm and llm.available()

    # ------------------------------------------------------------------ entry point
    def reply(self, msg):
        answer = self._reply(msg)
        if msg.strip() and not answer.startswith("Cleared the session"):
            self.s.history.append(msg.strip())
            self.s.history = self.s.history[-8:]
        return answer

    def _reply(self, msg):
        t = re.sub(r"\s+", " ", msg.strip().lower())
        if not t:
            return HELP
        if re.search(r"\b(start over|reset|new conversation|clear (?:everything|all|filters|restrictions))\b", t):
            self.s = Session()
            return "Cleared the session (search, restrictions and ingredient list)."
        if t in ("help", "?", "what can you do", "what can you do?"):
            return HELP
        if re.fullmatch(r"(?:hi+|hello|hey|hola|yo|good (?:morning|evening|afternoon)|thanks?|thank you)[.! ]*", t):
            return "Hello! Tell me a dish or ingredients (e.g. 'penne pasta', 'I have eggs and rice') - or type 'help'."
        if self.use_llm:
            out = self._reply_llm(msg)
            if out:
                return out
        out = self._unsupported(t) or self._route(msg, t)
        return out or ("I could not place that request. " + HELP)

    def _unsupported(self, t):
        """Attributes the dataset does not contain: refuse instead of inventing them."""
        if not re.search(r"calorie|nutrition|protein content|carbs?\b|fat content|sugar content|sodium|\bkcal\b|macro|"
                         r"cook(?:ing)? time|prep(?:aration)? time|total time|how long (?:does|do|to|will|is)|servings?\b|how much does .* cost|"
                         r"\bcost\b|\bprice\b|\brating|\breviews?\b|difficulty|healthy|healthiest", t):
            return None
        return self._unsupported_text(bool(re.search(r"time|how long", t)))

    def _unsupported_text(self, time_q):
        msg = ("The Recipe Box data only has, per recipe: title, ingredient lines, instruction text (and a picture link). It has NO "
               "nutrition values, cooking/prep times, servings, costs, ratings or difficulty, so I cannot give those and I will not estimate them.")
        rid = self.s.focus
        if rid and time_q:
            rec = db.get_recipe(self.con, rid)
            hits = re.findall(r"[^.]*\b\d+(?:\s*(?:-|to)\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?)\b[^.]*\.?", rec["instructions"] or "") if rec else []
            if hits:
                msg += (f"\nWhat the instruction text of [{rid}] {rec['title']} does mention (quoted, not a structured cooking time):\n"
                        + "\n".join(f"  - {h.strip()}" for h in hits[:6]))
        return msg

    def _ctx(self):
        s = self.s
        titles = []
        for i, rid in enumerate(s.results[:5], 1):
            r = self.con.execute("SELECT title FROM recipes WHERE id=?", (rid,)).fetchone()
            titles.append(f"#{i} {r[0]}" if r else "")
        focus = db.get_recipe(self.con, s.focus) if s.focus else None
        active_recipe = f"[{s.focus}] {focus['title']}" if focus else "none"
        return (f"mode={s.mode}; active search={s.filters.describe()}; active recipe={active_recipe}; "
                f"restrictions={[str(e) for e in s.exclude] or 'none'}; max_steps={s.max_steps}; "
                f"preference={s.prefer}; requested_results={s.top}; "
                f"user ingredients={[e['opts'][0] for e in s.have] or 'none'}; "
                f"last results: {'; '.join(titles) or 'none'}; "
                f"recent user turns={json.dumps(s.history[-6:], ensure_ascii=False)}")

    # ------------------------------------------------------------------ LLM path: plan -> execute in code -> verified summary
    def _reply_llm(self, msg):
        p = self._percentage_plan(msg) or planner.plan(msg, self._ctx())
        if not p:
            return None
        try:
            facts, narrate = self._exec_plan(p, msg)
        except Exception as e:                       # never let a planner mistake crash the chat: use the rule-based path
            return None
        if facts is None:
            return None
        tag = f"[query plan: {self._plan_line(p)}]"
        if not narrate:
            return facts + f"\n\n{tag}"
        summary, note = compose.summarize(msg, facts)
        if summary:
            return f"{summary}\n\n--- Retrieved data (what the answer above is based on) ---\n{facts}\n\n{tag} [answer: {note}]"
        return facts + f"\n\n{tag} [LLM wording not used: {note}]"

    def _percentage_plan(self, msg):
        """Route percentage questions to deterministic count statistics, never recipe search."""
        if not re.search(r"\b(?:percent(?:age)?|share|proportion|fraction)\b", msg.lower()):
            return None
        spec = self._spec(msg.lower())
        raw = {
            "action": "stats",
            "stat": {
                "type": "count",
                "contains_all": spec.include_all,
                "contains_any": spec.include_any,
                "exclude": [e.key if e.kind in ("cat", "ing") else str(e) for e in spec.exclude],
                "title_words": spec.title,
            },
        }
        return planner.validate(raw)

    def _plan_line(self, p):
        keep = {k: v for k, v in p.items() if v not in (None, [], False, "balanced", "that attribute")}
        return json.dumps(keep, ensure_ascii=False)

    def _ex(self, words):
        out = []
        for w in words:
            e = resolve_exclusion(w)
            if e and e not in out:
                out.append(e)
        return out

    def _ref_to_id(self, ref):
        s = self.s
        if not ref or ref.lower() in ("this", "that", "it", "current", "the recipe", "this recipe", "that recipe"):
            return s.focus
        m = re.fullmatch(r"#?\s*(\d+)", ref.strip())
        if m:
            n = int(m.group(1))
            return s.results[n - 1] if 1 <= n <= len(s.results) else None
        ids = nlu.extract_ids(ref.lower())
        if ids:
            row = self.con.execute("SELECT id FROM recipes WHERE lower(id)=?", (ids[0],)).fetchone()
            return row[0] if row else None
        like = "%" + ref.lower().strip() + "%"
        for rid in s.results:                               # prefer something already on screen
            r = self.con.execute("SELECT lower(title) FROM recipes WHERE id=?", (rid,)).fetchone()
            if r and ref.lower().strip() in r[0]:
                return rid
        row = self.con.execute(f"SELECT r.id FROM recipes r WHERE {UNIQUE} AND lower(r.title)=?", (ref.lower().strip(),)).fetchone() or \
              self.con.execute(f"SELECT r.id FROM recipes r WHERE {UNIQUE} AND lower(r.title) LIKE ? ORDER BY length(r.title) LIMIT 1", (like,)).fetchone()
        return row[0] if row else None

    def _exec_plan(self, p, raw):
        """-> (DATA text, narrate?) ; (None, _) means 'could not execute, use the rule-based parser'."""
        s = self.s
        a = p["action"]
        if a == "smalltalk":
            return "Hello! Tell me a dish, ingredients you have, or a question about the recipes (type 'help' for examples).", False
        if a == "reset":
            self.s = Session()
            return "Cleared the session (search, restrictions and ingredient list).", False
        if a == "unsupported":
            return self._unsupported_text("time" in p["attribute"].lower()), False
        if p["allow"]:
            return self._allow(self._ex(p["allow"])), False
        if a == "names":
            return (self._list_names(p["dish"]) if p["dish"] else None), False
        if a == "show":
            rid = self._ref_to_id(p["ref"])
            if not rid:
                return "I could not find which recipe you mean. Use its number from the last list (#2), its ID, or its exact title.", False
            parts = p["show_parts"] or ["ingredients", "instructions"]
            return self._show(raw, "show " + " ".join(parts), [rid.lower()], None), False
        if a == "stats":
            st = p["stat"]
            sp = analytics.Spec(include_all=nlu.ingredients_from(", ".join(st["all"])), include_any=nlu.ingredients_from(", ".join(st["any"])),
                                exclude=self._ex(st["exclude"]), title=re.findall(r"[a-z][a-z'\-]+", " ".join(st["title"]).lower()))
            c = self.con
            if st["type"] == "count":
                return analytics.count(c, sp), True
            if st["type"] == "ingredient_count_stats":
                return analytics.ing_count_stats(c, sp), True
            if st["type"] == "step_stats":
                return analytics.step_stats(c, sp), True
            if st["type"] == "common_ingredients":
                return analytics.common_ingredients(c, sp, top=(st["n"] if st["n"] != 5 else (p["top_n"] or 15)), skip_staples=st["skip_staples"]), True
            return analytics.rank_steps(c, sp, n=st["n"], fewest=(st["order"] == "fewest")), True
        if a == "match" or (a == "search" and not p["dish"] and not p["required"] and s.mode == "match" and not p["more"]):
            have = []
            for h in p["have"]:
                txt = " ".join(x for x in (f"{h['qty']:g}" if h["qty"] is not None else "", h["unit"] or "", h["name"]) if x)
                for e in parse_line(txt):
                    if e["opts"] and e["opts"][0] not in [x["opts"][0] for x in have]:
                        have.append(e)
            if not have and s.mode != "match":
                return None, False
            mp = {"ex": self._ex(p["exclude"]), "ms": p["max_steps"], "top": p["top_n"], "prefer": p["prefer"]}
            return self._match("", have or None, plan=mp), True
        if a == "search":
            if p["more"]:
                return self._search("more"), False
            dish = [w for w in re.findall(r"[a-z][a-z'\-]+", (p["dish"] or "").lower()) if w not in ("recipe", "recipes", "dish", "dishes")][:8]
            inc = nlu.ingredients_from(", ".join(p["required"]))
            if not (dish or inc or p["exclude"] or p["max_steps"]):
                return None, False
            return self._search_apply(dish, inc, self._ex(p["exclude"]), p["max_steps"]), False
        if a == "substitute":
            sb = p["substitute"]
            self._merge_ex(self._ex(p["exclude"]))
            if sb.get("choose") and s.last_adapt and not sb.get("target"):
                return self._substitute_choose(sb["choose"]), True
            tgt = nlu.ingredients_from(sb["target"])
            if not tgt:
                return None, False
            rid = self._ref_to_id(sb["recipe"]) if sb["recipe"].lower() not in ("this", "that", "it") else s.focus
            text = f"replace {tgt[0]} in {rid}" if rid else f"replace {tgt[0]} in the {sb['recipe']} recipe"
            out = self._substitute(text, text.lower())
            if out and sb.get("choose") and s.last_adapt:
                out = self._substitute_choose(sb["choose"]) or out
            return out, True
        return None, False

    # ------------------------------------------------------------------ routing
    def _route(self, raw, t):
        s = self.s
        exact = self._exact_title(raw)
        if exact:
            return exact
        allow = nlu.extract_allow(t) if re.search(r"restriction|filter|again|\b(?:fine|ok|okay)\b|i can (?:now )?(?:have|eat)|\ballow\b|ignore", t) \
            and not re.search(r"replac|substitut|swap", t) else []
        if allow:
            return self._allow(allow)
        if re.search(r"\b(?:substitut\w*|replac\w*|swap\w*|instead of|take out|get rid of|leave out|omit|eliminate|remove)\b", t) \
                and not re.search(r"how many|average|median|most common", t):
            r = self._substitute(raw, t)
            if r:
                return r
        if s.last_adapt and re.match(r"^(?:ok(?:ay)?,? )?(?:use|try|go with|pick|choose|what about)\s+(.+?)[.!?]*$", t):
            m = re.match(r"^(?:ok(?:ay)?,? )?(?:use|try|go with|pick|choose|what about)\s+(.+?)[.!?]*$", t)
            r = self._substitute_choose(m.group(1))
            if r:
                return r
        lm = re.fullmatch(r"(?:list|names?|all|dishes?|show all|list all|all the)?\s*(?:names? of |dish names? (?:for|with|of) )?([a-z][a-z'-]+)(?: recipes| dishes| names)?[.!?]*", t)
        if lm and lm.group(1) not in ("more", "next", "help", "reset", "quit") and not re.fullmatch(r"(?:more|next)", t):
            return self._list_names(lm.group(1))
        have = nlu.parse_have(t)
        if have:
            return self._match(t, have)
        if re.search(r"how many|number of recipes|what percent|percentage|\bshare\b|\bproportion\b|\bfraction\b|"
                     r"\baverage\b|\bmean\b|\bmedian\b|most common|common ingredients|"
                     r"popular ingredients|fewest|least|lowest|shortest|longest|most (?:instruction )?steps|rank", t) \
                and not re.search(r"\b(?:i have|i've got)\b", t):
            r = self._stats(raw, t)
            if r:
                return r
        ids = nlu.extract_ids(raw.lower())
        ordn = nlu.extract_ordinal(t)
        if (ids or ordn or re.search(r"\b(ingredients?|instructions?|directions?|steps?|method|full recipe|that one|this one|the recipe)\b", t)) \
                and re.search(r"\b(show|give|list|display|see|what (?:are|is)|print|read|how many steps|tell me)\b|^ingredients|^instructions", t):
            r = self._show(raw, t, ids, ordn)
            if r:
                return r
        if s.mode == "match" and not nlu.extract_dish(t) and self._has_constraints(t):
            return self._match(t, None)
        return self._search(t)

    # ------------------------------------------------------------------ helpers
    def _exact_title(self, raw):
        title = re.sub(r"^(?:find|show|open|get|give me|i want|recipe for)\s+", "", raw.strip().strip("\"'.!? "), flags=re.I)
        if len(title.split()) < 2:
            return None
        rows = self.con.execute(f"SELECT r.id FROM recipes r WHERE {UNIQUE} AND lower(r.title)=?", (title.lower(),)).fetchall()
        if not rows:
            return None
        self.s.results = [r[0] for r in rows]
        self.s.focus = rows[0][0]
        self.s.mode = "search"
        out = self._show(raw, "show ingredients and instructions", [], 1)
        extra = f"\n(+{len(rows) - 1} more recipe(s) with exactly this title: {', '.join(r[0] for r in rows[1:])})" if len(rows) > 1 else ""
        return "Exact title match.\n" + out + extra
    def _has_constraints(self, t):
        return bool(nlu.extract_exclusions(t) or nlu.extract_max_steps(t) or re.search(r"\bprefer|fewest|fewer|quick", t))

    def _merge_ex(self, new):
        added = []
        for e in new:
            if e not in self.s.exclude:
                self.s.exclude.append(e)
                added.append(e)
        return added

    def _allow(self, allow):
        gone = [e for e in allow if e in self.s.exclude]
        for e in gone:
            self.s.exclude.remove(e)
        self.s.filters.exclude = list(self.s.exclude)
        if not gone:
            return "None of those were active restrictions, so nothing changed."
        msg = "Removed restriction(s): " + ", ".join(str(e) for e in gone) + "."
        if self.s.mode == "search" and (self.s.filters.dish or self.s.filters.include):
            self.s.offset = 0
            return msg + "\n" + self._run_search()
        return msg

    # ------------------------------------------------------------------ search
    def _search(self, t):
        s = self.s
        if re.fullmatch(r"(?:more|next|show more|next page|more please|next ones?)[.!?]*", t):
            if s.mode == "list":
                s.names_offset += 60
                return self._page_names()
            if s.mode != "search":
                return "There is no active search to continue."
            s.offset += 5
            return self._run_search()
        new_ex = nlu.extract_exclusions(t)
        ms = nlu.extract_max_steps(t)
        dish = nlu.extract_dish(t)
        inc = nlu.extract_include(t)
        if not (dish or inc or new_ex or ms):
            return None
        return self._search_apply(dish, inc, new_ex, ms)

    def _search_apply(self, dish, inc, new_ex, ms):
        s = self.s
        refine_only = not dish
        if refine_only and not (s.filters.dish or s.filters.include):
            self._merge_ex(new_ex)
            if ms:
                s.max_steps = ms
            return "Noted: " + (", ".join(str(e) for e in s.exclude) or "no restriction") + ". Tell me what dish to search for and I will apply it."
        if refine_only:
            self._merge_ex(new_ex)
            for i in inc:
                if i not in s.filters.include:
                    s.filters.include.append(i)
            if ms:
                s.max_steps = ms
        else:                                  # new dish: restrictions persist, per-search limits reset
            s.filters = search.Filters(dish=dish, include=inc)
            s.max_steps = ms
            self._merge_ex(new_ex)
        s.mode = "search"
        s.offset = 0
        return self._run_search()

    def _run_search(self):
        s = self.s
        f = s.filters
        f.exclude, f.max_steps = list(s.exclude), s.max_steps
        r = search.search(self.con, f, limit=s.offset + 5)
        shown = r["results"][s.offset:s.offset + 5]
        restrictions = "; ".join(str(ex) for ex in f.exclude) or "None"
        head = [
            "## Recipe search",
            "",
            f"- **Dish / title query:** {' '.join(f.dish) or 'None'}",
            f"- **Required ingredients:** {', '.join(f.include) or 'None'}",
            f"- **Restrictions:** {restrictions}",
            f"- **Step limit:** {f'≤ {f.max_steps}' if f.max_steps else 'None'}",
            f"- **Eligible recipes:** {r['total']:,}",
            f"- **Retrieval:** {r['candidates']:,} candidates via {r['how']}"
            + ("; candidate limit reached" if r["capped"] else ""),
        ]
        if not shown and not s.offset and f.include and not r["total"]:
            # "<dish> with <x>" may be part of the dish NAME (e.g. '... with Maggi Ranch Sauce'): retry as one phrase
            g = search.Filters(dish=list(f.dish) + [w for i in f.include for w in i.split()])
            g.exclude, g.max_steps = f.exclude, f.max_steps
            r2 = search.search(self.con, g, limit=s.offset + 5)
            if r2["results"]:
                phrase = " ".join(f.include)
                f.dish, f.include = g.dish, []
                r, shown = r2, r2["results"]
                head = [
                    "## Recipe search",
                    "",
                    f"> No recipe has `{phrase}` as an ingredient, so it was treated as part of the dish name.",
                    "",
                    f"- **Dish / title query:** {' '.join(f.dish)}",
                    f"- **Restrictions:** {'; '.join(str(ex) for ex in f.exclude) or 'None'}",
                    f"- **Step limit:** {f'≤ {f.max_steps}' if f.max_steps else 'None'}",
                    f"- **Eligible recipes:** {r['total']:,}",
                    f"- **Retrieval:** {r['candidates']:,} candidates via {r['how']}"
                    + ("; candidate limit reached" if r["capped"] else ""),
                ]
        if not shown:
            if s.offset and r["total"]:
                return "\n".join(head + ["", "No more results."])
            hint = []
            if f.exclude or f.max_steps or f.include:
                g = search.Filters(dish=f.dish)
                r0 = search.search(self.con, g, limit=1)
                if r0["total"]:
                    hint = [
                        "",
                        f"Without your restrictions, {r0['total']:,} recipes match the dish, but none satisfy all current constraints.",
                        "No restriction was relaxed. Say **reset** or remove a restriction to broaden the search.",
                    ]
            return "\n".join(head + ["", "## Results", "", "No recipe matches."] + hint)
        s.results = r["all_ids"]
        s.focus = shown[0]["id"]
        lines = head + [
            "",
            f"## Results {s.offset + 1}-{s.offset + len(shown)} of {r['total']:,}",
            "",
        ]
        for i, rec in enumerate(shown, s.offset + 1):
            lines.extend([
                f"### {i}. {rec['title']}",
                "",
                f"- **Recipe ID:** `{rec['id']}`",
                f"- **Steps:** {rec['n_steps']} | **Ingredient lines:** {len(rec['lines'])}",
            ])
            if rec.get("evidence"):
                lines.append("- **Required ingredient evidence:** " + "; ".join(dict.fromkeys(rec["evidence"])))
            result_audit = rec.get("audit") or {}
            for label, ingredient_line, _ in result_audit.get("exceptions", []):
                lines.append(f"- **Allowed form ({label}):** {ingredient_line}")
            for label, ingredient_line, _ in result_audit.get("cautions", []):
                lines.append(f"- **Check label ({label}):** {ingredient_line} may contain it")
            if f.exclude and not (result_audit.get("cautions") or result_audit.get("exceptions")):
                lines.append(f"- **Restriction check:** no text match in {len(rec['lines'])} ingredient lines")
            lines.append("")
        if s.offset == 0:
            top = db.get_recipe(self.con, shown[0]["id"])
            lines.extend([
                "",
                f"## Featured recipe: {top['title']}",
                "",
                f"**Recipe ID:** `{top['id']}`",
                "",
                "### Ingredients",
                "",
            ])
            lines.extend(f"- {ingredient}" for ingredient in top["lines"])
            lines.extend(["", "### Instructions", ""])
            lines.extend(f"{i}. {step}" for i, step in enumerate(split_steps(top["instructions"]), 1))
            lines.append("")
        lines.extend([
            "",
            "**Next:** say `more` for more results, `show #N` for a recipe, or add a restriction to refine.",
        ])
        return "\n".join(lines)

    # ------------------------------------------------------------------ name listing
    def _list_names(self, word):
        s = self.s
        f = search.Filters(dish=word.split())
        f.exclude = list(s.exclude)
        r = search.search(self.con, f, limit=1)
        ids = r["all_ids"]
        if not ids:
            return f"No dish in the database has '{word}' in its title or ingredients."
        rows = []
        for k in range(0, len(ids), 900):
            ch = ids[k:k + 900]
            rows += self.con.execute(f"SELECT id,title FROM recipes WHERE id IN ({','.join('?'*len(ch))})", ch).fetchall()
        rows.sort(key=lambda x: x[1].lower())
        s.names, s.names_offset, s.mode = [(a, b) for a, b in rows], 0, "list"
        s.results = [a for a, _ in s.names]          # so 'show #N' works with the numbers printed below
        s.focus = None
        fn = f"names_{re.sub(r'[^a-z0-9]+', '_', word)}.txt"
        try:
            with open(fn, "w", encoding="utf-8") as fh:
                fh.write("\n".join(f"{i}. {b}   [{a}]" for i, (a, b) in enumerate(s.names, 1)))
            saved = f" Complete list also saved to {fn} (with IDs)."
        except OSError:
            saved = ""
        head = (f"{len(s.names):,} dishes for '{word}' (by {r['how']}{', capped at ' + str(search.CAP) if r['capped'] else ''}"
                + (f"; your restrictions applied: {', '.join(str(e) for e in s.exclude)}" if s.exclude else "") + f").{saved}")
        return head + "\n" + self._page_names()

    def _page_names(self):
        s = self.s
        part = s.names[s.names_offset:s.names_offset + 60]
        if not part:
            return "No more names."
        out = [f"{i}. {b}" for i, (a, b) in enumerate(part, s.names_offset + 1)]
        end = s.names_offset + len(part)
        out.append(f"-- {s.names_offset + 1}-{end} of {len(s.names):,}. 'more' = next 60 | 'show #N' = that dish in full | "
                   f"or type a command like 'find <exact name> no dairy'.")
        return "\n".join(out)

    # ------------------------------------------------------------------ show
    def _resolve_id(self, raw_ids, ordn):
        s = self.s
        for rid in raw_ids:
            row = self.con.execute("SELECT id FROM recipes WHERE lower(id)=?", (rid,)).fetchone()
            if row:
                return row[0]
        if ordn and 1 <= ordn <= len(s.results):
            return s.results[ordn - 1]
        return s.focus

    def _show(self, raw, t, ids, ordn):
        rid = self._resolve_id(ids, ordn)
        if not rid:
            return "Which recipe? Search first, or give a recipe ID."
        rec = db.get_recipe(self.con, rid)
        if not rec:
            return f"No recipe with ID {rid}."
        self.s.focus = rid
        steps = split_steps(rec["instructions"])
        want_i = bool(re.search(r"ingredient", t))
        want_s = bool(re.search(r"instruction|direction|step|method", t))
        if not want_i and not want_s:
            want_i = want_s = True
        L = [f"[{rec['id']}] {rec['title']}  ({len(steps)} steps by the step-counting rule, {len(rec['lines'])} ingredient lines)"]
        if want_i:
            L += ["Ingredients (original text):"] + [f"  - {x}" for x in rec["lines"]]
        if want_s:
            L += ["Instructions (original text):"] + [f"  {i}. {x}" for i, x in enumerate(steps, 1)]
        if self.s.exclude:
            a = audit(rec["lines"], rec["parsed"], self.s.exclude)
            if a["violations"]:
                L.append("NOTE: this recipe CONFLICTS with your restrictions: " + "; ".join(f"{lab}: '{ln}'" for lab, ln, _ in a["violations"]))
        return "\n".join(L)

    # ------------------------------------------------------------------ stats
    def _spec(self, t):
        s = self.s
        sp = analytics.Spec()
        inc = nlu.extract_include(t, plain_with=True)
        if not inc:
            clause = re.search(r"\b(?:use|uses)\s+([a-z][a-z ,'-]*?)(?:\s+together\b|[,.?!]|$)", t)
            if clause:
                inc = nlu.ingredients_from(clause.group(1))
        if not inc:
            subjects = (
                r"\b(?:of|among)\s+(?:(?:all|the)\s+)?([a-z][a-z ,'-]*?)\s+(?:recipes?|dishes?)\b",
                r"\b(?:are|is)\s+([a-z][a-z ,'-]*?)\s+(?:recipes?|dishes?)\b",
            )
            for pattern in subjects:
                subject = re.search(pattern, t)
                if subject:
                    words = subject.group(1).strip()
                    if words not in ("all", "the", "all the"):
                        inc = nlu.ingredients_from(words)
                        if not inc and words not in ("vegan", "vegetarian"):
                            sp.title = re.findall(r"[a-z][a-z'\-]+", words)
                    if inc or sp.title:
                        break
        clause = re.search(r"(?:contain\w*|with|includ\w*|using|has|have)\s+(?:either\s+)?([a-z ,'-]+?)(?:[,.?!]|$|\s+(?:which|what|how|and what|and how))", t)
        any_mode = bool(clause and re.search(r"\bor\b", clause.group(1)) and not re.search(r"\band\b", clause.group(1)))
        if inc and any_mode:
            sp.include_any = inc
        else:
            sp.include_all = inc
        sp.exclude = nlu.extract_exclusions(t)
        if re.search(r"\b(?:those|these|them|current search|that search|of the results)\b", t) and s.mode == "search":
            f = s.filters
            sp.title, sp.include_all = list(f.dish), list(dict.fromkeys(sp.include_all + f.include))
            sp.exclude = list(dict.fromkeys(sp.exclude + s.exclude))
        return sp

    def _stats(self, raw, t):
        sp = self._spec(t)
        c = self.con
        if re.search(r"how many|number of recipes|what percent|percentage|\bshare\b|\bproportion\b|\bfraction\b|\bcount\b", t) \
                and not re.search(r"how many steps", t):
            return analytics.count(c, sp)
        if re.search(r"average|mean|median", t) and re.search(r"ingredient", t):
            return analytics.ing_count_stats(c, sp)
        if re.search(r"average|mean|median", t) and re.search(r"steps?", t):
            return analytics.step_stats(c, sp)
        if re.search(r"common|popular|frequent|top", t) and re.search(r"ingredient", t):
            return analytics.common_ingredients(c, sp, top=nlu.extract_top_n(t, 15),
                                                skip_staples=bool(re.search(r"excluding salt|without salt|skip staples|ignore (?:salt|staples)|no salt", t)))
        if re.search(r"steps?", t) and re.search(r"fewest|least|lowest|shortest|simplest|most|longest|highest|rank", t):
            return analytics.rank_steps(c, sp, n=nlu.extract_top_n(t, 5), fewest=bool(re.search(r"fewest|least|lowest|shortest|simplest", t)))
        return None

    # ------------------------------------------------------------------ match (Task 2)
    def _match(self, t, have, plan=None):
        s = self.s
        if plan is not None:                       # structured plan from the LLM planner
            if have:
                s.have, s.mode = have, "match"
                s.top, s.max_steps, s.prefer = plan.get("top") or 5, plan.get("ms"), plan.get("prefer") or "balanced"
            else:
                if plan.get("ms"):
                    s.max_steps = plan["ms"]
                if plan.get("top"):
                    s.top = plan["top"]
                if plan.get("prefer") not in (None, "balanced"):
                    s.prefer = plan["prefer"]
            self._merge_ex(plan.get("ex", []))
        elif have is not None:
            s.have, s.mode = have, "match"
            s.top = nlu.extract_top_n(t, 5)
            s.max_steps = nlu.extract_max_steps(t)
            s.prefer = nlu.prefer(t)
            ex_before = []
            self._merge_ex(nlu.extract_exclusions(re.sub(r"^.*?(?=\b(?:suggest|find|with no|no |without|exclude)\b)", "", t, count=1)
                                                    if nlu.parse_have(t) else t))
        else:
            self._merge_ex(nlu.extract_exclusions(t))
            ms = nlu.extract_max_steps(t)
            if ms:
                s.max_steps = ms
            if nlu.prefer(t) != "balanced":
                s.prefer = nlu.prefer(t)
            n = nlu.extract_top_n(t, 0)
            if n:
                s.top = n
        notes = []
        keep = []
        for e in s.have:                          # a hard exclusion that contradicts something the user "has"
            clash = None
            for ex in s.exclude:
                if ex.kind == "ing" and ex.key in e["opts"]:
                    clash = ex
                elif ex.kind == "cat":
                    from .restrict import check_line
                    if check_line(e["opts"][0], ex.key)[0] == "violates":
                        clash = ex
            if clash:
                notes.append(f"'{e['opts'][0]}' removed from your available ingredients ({clash})")
            else:
                keep.append(e)
        s.have = keep
        if not s.have:
            return "After applying your exclusions there are no ingredients left to match with."
        res = matcher.match(self.con, s.have, s.exclude, max_steps=s.max_steps, prefer=s.prefer, top=s.top)
        wr, wc, ws = res["weights"]
        L = [f"Ingredient match | you have: {', '.join(e['opts'][0] for e in s.have)}",
             "Hard constraints: " + ("; ".join([str(e) for e in s.exclude] + ([f"<= {s.max_steps} steps"] if s.max_steps else [])) or "none"),
             f"Score = 100 x ({wr}*recall + {wc}*coverage + {ws}*step_ease); preference = {s.prefer}. Salt/water/black pepper assumed available.",
             (f"{res['n_eligible']:,} eligible recipes of {res['n_candidates']:,} that share an ingredient with you." if res["n_eligible"] is not None
              else f"Best-scoring eligible recipes among {res['n_candidates']:,} that share an ingredient with you (all hard constraints verified on each result).")]
        L += ["Note: " + n for n in notes]
        if not res["eligible"]:
            L.append("\nNO MATCH FOUND that satisfies every hard constraint. Nothing below satisfies them all:")
            for i, (rec, reasons) in enumerate(res["closest_violating"], 1):
                L.append(matcher.format_result(rec, i, reasons))
            if not res["closest_violating"]:
                L.append("(no recipe even shares an ingredient with your list)")
            return "\n".join(L)
        s.results = [r["id"] for r in res["eligible"]]
        s.focus = s.results[0]
        if res["n_eligible"] is not None and res["n_eligible"] < s.top:
            L.append(f"Only {res['n_eligible']} recipe(s) satisfy all constraints; I did not pad the list with ineligible ones.")
        for i, rec in enumerate(res["eligible"][:s.top], 1):
            L.append(matcher.format_result(rec, i))
        L.append("Quantities: " + ("compared where units are comparable (see per-ingredient flags)." if any(e.get("q") is not None for e in s.have)
                                  else "none given, so only name-level matches were checked; quantity sufficiency NOT verified."))
        return "\n".join(L)

    # ------------------------------------------------------------------ substitution (Task 3)
    def _target(self, t):
        for rx in (r"(?:replace|substitut\w*(?: for)?|swap(?: out)?|remove|take out|get rid of|leave out|omit|eliminate)\s+(?:the\s+|all\s+|any\s+)?([a-z ]+?)(?=\s+(?:in|from|with|for|using|without|and|but|so|by)\b|[.,?!]|$)",
                   r"instead of\s+([a-z ]+?)(?=\s+(?:in|from|for|with)\b|[.,?!]|$)"):
            m = re.search(rx, t)
            if m:
                got = nlu.ingredients_from(m.group(1))
                if got:
                    return got[0]
        return None

    def _pick_recipe(self, raw, t, target):
        s = self.s
        fam = set(substitute.TABLE.get(substitute.TABLE_KEY.get(target, target), {}).get("family", set())) | {target}
        has = lambda rid: (lambda r: r and any(set(e["opts"]) & fam for e in r["parsed"]))(db.get_recipe(self.con, rid))
        ids = nlu.extract_ids(raw.lower())
        if ids:
            rid = self._resolve_id(ids, None)
            return rid
        m = re.search(r"(?:this|that|the|my)\s+([a-z ]+?)\s+recipe", t)
        phrase = [w for w in (m.group(1).split() if m else []) if w not in ("this", "that", "same", "current", "first", "last")]
        if not phrase or True:
            for rid in ([s.focus] if s.focus else []) + s.results:
                r = db.get_recipe(self.con, rid) if rid else None
                if r and has(rid) and all(w in r["title"].lower() for w in phrase):
                    return rid
        if phrase:
            f = search.Filters(dish=phrase)
            rows, _ = search.candidate_rows(self.con, f)
            for row in rows:
                if has(row["id"]):
                    return row["id"]
        return None

    def _substitute(self, raw, t):
        target = self._target(t)
        if not target:
            return None
        new_ex = nlu.extract_exclusions(t)
        self._merge_ex(new_ex)
        rid = self._pick_recipe(raw, t, target)
        if not rid:
            return (f"I could not find a recipe containing '{target}' to adapt. Give a recipe ID or name it "
                    f"(e.g. 'replace {target} in the banana bread recipe'); I only adapt recipes that exist in the dataset.")
        self.s.focus = rid
        res = substitute.adapt(self.con, rid, target, self.s.exclude, dataset_only=not re.search(r"external|web|internet|any ingredient", t))
        self.s.last_adapt = {"rid": rid, "target": target}
        return self._fmt_adapt(res)

    def _substitute_choose(self, what):
        la = self.s.last_adapt
        res = substitute.adapt(self.con, la["rid"], la["target"], self.s.exclude, choose=what.strip())
        if res.get("pick") and what.strip().lower() not in res["pick"]["spec"]["display"].lower() and what.strip().lower() != res["pick"]["spec"]["canon"]:
            return f"'{what}' is not one of the eligible candidates for this change (see the candidate list above)."
        return self._fmt_adapt(res)

    def _fmt_adapt(self, res):
        return substitute.format_adaptation(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/recipes.db")
    ap.add_argument("--script", help="text file: one user message per line (# comments, blank = skip)")
    ap.add_argument("--no-llm", action="store_true", help="rule-based mode (no Ollama / Gemini)")
    ap.add_argument("--llm", choices=["auto", "ollama", "gemini", "none"], help="provider order override (default auto: Ollama, then Gemini)")
    a = ap.parse_args()
    if a.no_llm:
        os.environ["LLM_PROVIDER"] = "none"
    elif a.llm:
        os.environ["LLM_PROVIDER"] = a.llm
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    bot = Bot(a.db, use_llm=not a.no_llm)
    if a.script:
        for line in open(a.script, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            print(f"\n>>> {line}\n{bot.reply(line)}")
        return
    print(f"Recipe assistant. {llm.status()}. Mode: " + ("LLM planner + verified summaries (rule-based fallback)" if bot.use_llm else "rule-based only")
          + ". Type 'help' or 'quit'.")
    while True:
        try:
            msg = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            break
        if msg.strip().lower() in ("quit", "exit", "q"):
            break
        print(bot.reply(msg))


if __name__ == "__main__":
    main()

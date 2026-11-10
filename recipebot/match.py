"""Task 2 - ingredient-based matching with an explainable score.

score = 100 x ( w_r*recall + w_c*coverage + w_s*step_ease )
  recall    = (# of your ingredients that the recipe uses) / (# of your ingredients)
  coverage  = matched required lines / all required lines   (1.0 = nothing extra to buy)
  step_ease = 1 / (1 + steps/6)
weights: balanced .45/.45/.10 | prefer 'missing' .30/.60/.10 | prefer 'steps' .35/.35/.30
Hard constraints (exclusions, max steps, max missing) are filters, never score penalties.
Salt, water and black pepper are ASSUMED available (reported as such, not counted as missing).
"""
from .db import UNIQUE, row_to_recipe
from .normalize import satisfies, STAPLES, IMPLIES, fmt_qty
from .restrict import audit

WEIGHTS = {"balanced": (.45, .45, .10), "missing": (.30, .60, .10), "steps": (.35, .35, .30)}


def _needs_for(have):
    s = set(have)
    for h in have:
        s |= IMPLIES.get(h, set())
    return s


def _qty_status(have_e, need_e):
    if have_e is None or have_e.get("q") is None:
        return "name-level only"
    if need_e.get("q") is None or have_e["dim"] != need_e["dim"] or (need_e["dim"] == "cnt" and have_e["unit"] != need_e["unit"]):
        return "quantity not comparable"
    return "enough" if have_e["q"] + 1e-9 >= need_e["q"] else f"SHORT (have {fmt_qty(have_e['q'])}, need {fmt_qty(need_e['q'])} in base units)"


def evaluate(rec, have_entries, assume_staples=True):
    have_by = {e["opts"][0]: e for e in have_entries}
    matched, missing, assumed, used = [], [], [], set()
    for e in rec["parsed"]:
        if e.get("o"):
            continue
        hit = next((h for h in have_by if any(satisfies(h, o) for o in e["opts"])), None)
        label = rec["lines"][e["i"]] if e["i"] < len(rec["lines"]) else e["opts"][0]
        if hit:
            used.add(hit)
            matched.append((label, hit, _qty_status(have_by[hit], e)))
        elif assume_staples and all(o in STAPLES for o in e["opts"]):
            assumed.append(label)
        else:
            missing.append(label + (f"  (or: {', '.join(e['opts'][1:])})" if len(e["opts"]) > 1 else ""))
    return matched, list(dict.fromkeys(missing)), list(dict.fromkeys(assumed)), used


def match(con, have_entries, exclusions=(), max_steps=None, max_missing=None, prefer="balanced", top=5):
    """Two phases, same results as scoring everything:
    1) cheap score of every candidate from the `parsed` column only; 2) walk candidates best-first, load the full
    record, audit hard constraints, stop once `top` eligible recipes are found (exact count only if we scanned all)."""
    import json
    have = [e["opts"][0] for e in have_entries]
    needs = sorted(_needs_for(have))
    ids = [r[0] for r in con.execute(
        f"SELECT DISTINCT recipe_id FROM recipe_ingredients WHERE is_alt=0 AND canon IN ({','.join('?'*len(needs))})", needs)]
    wr, wc, ws = WEIGHTS[prefer]
    accepted = {}
    for h in have:
        for nd in {h} | IMPLIES.get(h, set()):
            accepted.setdefault(nd, h)
    scored = []
    for k in range(0, len(ids), 900):
        chunk = ids[k:k + 900]
        for rid, n_steps, parsed in con.execute(
                f"SELECT r.id,r.n_steps,r.parsed FROM recipes r WHERE {UNIQUE} AND r.id IN ({','.join('?'*len(chunk))})", chunk):
            used, nm, nmiss = set(), 0, 0
            for e in json.loads(parsed):
                if e.get("o"):
                    continue
                hit = next((accepted[o] for o in e["opts"] if o in accepted), None)
                if hit:
                    used.add(hit)
                    nm += 1
                elif not all(o in STAPLES for o in e["opts"]):
                    nmiss += 1
            if not used:
                continue
            tot = nm + nmiss
            sc = 100 * (wr * len(used) / len(have) + wc * (nm / tot if tot else 1.0) + ws / (1 + n_steps / 6))
            scored.append((-sc, nmiss, n_steps, rid))
    scored.sort(key=lambda x: (round(x[0], 9), x[1], x[2], x[3]))
    eligible, blocked, exhausted = [], [], True
    for k in range(0, len(scored), 200):
        part = scored[k:k + 200]
        rows = {r["id"]: r for r in con.execute(f"SELECT r.* FROM recipes r WHERE r.id IN ({','.join('?'*len(part))})", [x[3] for x in part])}
        for neg, nmiss, n_steps, rid in part:
            rec = row_to_recipe(rows[rid])
            matched, missing, assumed, used = evaluate(rec, have_entries)
            tot = len(matched) + len(missing)
            recall, cov, ease = len(used) / len(have), (len(matched) / tot if tot else 1.0), 1 / (1 + rec["n_steps"] / 6)
            rec.update(matched=matched, missing=missing, assumed=assumed, used=sorted(used), recall=recall, coverage=cov, ease=ease,
                       score=100 * (wr * recall + wc * cov + ws * ease))
            reasons = [f"{lab}: '{ln}'" for lab, ln, _ in audit(rec["lines"], rec["parsed"], exclusions)["violations"]]
            if max_steps and rec["n_steps"] > max_steps:
                reasons.append(f"{rec['n_steps']} steps > limit {max_steps}")
            if max_missing is not None and len(missing) > max_missing:
                reasons.append(f"{len(missing)} missing > limit {max_missing}")
            if reasons:
                if len(blocked) < 3:
                    blocked.append((rec, reasons))
            else:
                eligible.append(rec)
        if len(eligible) >= top:
            exhausted = k + 200 >= len(scored)
            break
    return {"eligible": eligible[:top], "n_eligible": len(eligible) if exhausted else None, "n_candidates": len(scored),
            "closest_violating": blocked if not eligible else [], "weights": (wr, wc, ws), "prefer": prefer}


def format_result(rec, rank, reasons=None):
    L = [f"{rank}. [{rec['id']}] {rec['title']}  - score {rec['score']:.1f}, {rec['n_steps']} steps"]
    if reasons:
        L.append("   !! VIOLATES YOUR CONSTRAINTS: " + " | ".join(reasons))
    L.append("   matched: " + ("; ".join(f"{ln} <- your {h} [{q}]" for ln, h, q in rec["matched"]) or "-"))
    L.append("   missing / extra required: " + ("; ".join(rec["missing"]) or "none"))
    if rec["assumed"]:
        L.append("   assumed pantry staples: " + "; ".join(rec["assumed"]))
    L.append(f"   why: uses {len(rec['used'])} of your ingredients (recall {rec['recall']:.2f}); {len(rec['matched'])} of "
             f"{len(rec['matched'])+len(rec['missing'])} required lines covered (coverage {rec['coverage']:.2f}); step ease {rec['ease']:.2f}")
    return "\n".join(L)

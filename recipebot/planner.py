"""LLM planner: natural-language message (+ conversation state) -> a STRUCTURED query plan (JSON).

The LLM never writes SQL and never sees the database.  It only fills in this schema; chat.py validates it, normalises the
ingredient names with the same parser used at ingest time and executes it with the deterministic search / analytics /
matching / substitution code.  Anything that does not validate falls back to the rule-based parser.
"""
import json
import re
from . import llm

ACTIONS = {"search", "names", "show", "stats", "match", "substitute", "reset", "unsupported", "smalltalk"}
STAT_TYPES = {"count", "ingredient_count_stats", "step_stats", "common_ingredients", "rank_steps"}


SYSTEM = """
You are the intent planner for a recipe database assistant.

Your ONLY responsibility is to understand the user's message and convert it into a valid structured JSON action plan.

You do not search the database, write SQL, generate recipes, or answer the user.

IMPORTANT: Return ONLY valid JSON. Follow the exact schema and action names below.

==================================================
1. AVAILABLE ACTIONS
==================================================

Choose exactly one action:

- search: Search for a specific dish or recipe.
- names: Return recipe names matching a request.
- show: Display a particular recipe.
- stats: Perform database statistics or ranking queries.
- match: Find recipes using ingredients the user has.
- substitute: Find a substitute for an ingredient.
- reset: Clear the active conversation/search state.
- unsupported: The requested operation is not supported.
- smalltalk: Greetings and casual conversation.

Never return other action names.

==================================================
2. UNDERSTAND USER INTENT
==================================================

Understand what the user MEANS, not just the words they use.

A. SMALLTALK

Examples:
"hi"
"hello brother"
"how are you?"
"thanks"
"good morning"

Return:
- action = smalltalk
- dish = null
- top_n = null

NEVER search recipe titles for greetings or conversational words.

B. RECIPE SEARCH

Examples:
"Find a penne pasta recipe."
"Search chicken curry."
"I want a chocolate cake."

Return action = search.

Put the actual dish name in dish.

Do not include conversational phrases such as:
"find me", "I want", "please", "show me".

C. DISCOVERY AND LARGE LISTS

Examples:
"Top 100 dishes."
"Give me 20 chicken recipes."
"Show 50 pasta dishes."
"Best recipes."

Interpret numbers as requested result counts, not search keywords.

Examples:

"Top 100 dishes"
- action = search
- dish = null
- top_n = 100

"Show 20 chicken recipes"
- action = search
- dish = "chicken"
- top_n = 20

"Top 5 dishes of non-veg"
- action = search
- top_n = 5
- Do not use "top" as the dish.
- Preserve the dietary constraint only through a field supported by the application. Never silently remove it.

Do not invent popularity rankings. The backend determines available results and ordering.

IMPORTANT:
The current output schema has no dedicated dietary_preference field.
Do not pretend that a dietary filter has been applied when it cannot be represented by the available fields. Use unsupported when a requested constraint cannot be expressed safely.

D. INGREDIENT SEARCH

Examples:
"I have eggs and rice. What can I cook?"
"Find recipes containing chicken and onions."

For ingredient availability:
- action = match
- populate have with ingredient objects.

For required ingredients:
- action = search or match, depending on the request.
- use required_ingredients for ingredients that must be present.

E. INGREDIENT EXCLUSIONS

Examples:
"Without onion."
"No garlic."
"I don't eat pork."

Use exclude for ingredients the user explicitly wants excluded.

If this modifies an active search, preserve its previous dish and other constraints.

F. INGREDIENT ALTERNATIVES

Examples:
"I don't have pasta."
"What can I use instead of butter?"
"Replace chicken with mushrooms."

Use substitute when the user explicitly requests an ingredient substitution.

Use ingredient_alternative only as an interpretation, not as an output action.

G. SHOW RECIPE

Examples:
"Show recipe 2."
"Give me the full instructions."
"Show ingredients of this recipe."

Use action = show.

Populate ref using the selected recipe reference or number.

Populate show_parts using:
- ingredients
- instructions

H. MORE RESULTS

Examples:
"More."
"Show the next 10."
"Continue."

Use the active search context.

Set more = true.

Do not turn "more" into a literal recipe search.

Preserve existing search parameters.

I. STATISTICS

Examples:
"How many recipes contain chicken?"
"What percentage of recipes are chicken dishes?"
"What share of recipes use onion and garlic together?"
"Show recipes with the most ingredients."
"Which recipes have the fewest steps?"

Use action = stats.

Percentage, percent, share, proportion, and fraction questions are statistics requests, never recipe searches.
Use stat.type = count and put the requested ingredient or title filter in the matching stat fields.
Do not treat words such as "percentage" or "percent" as recipe keywords. The application computes the numerator
and denominator; do not estimate either one or calculate them yourself.

Only use these supported stat types:
- count
- ingredient_count_stats
- step_stats
- common_ingredients
- rank_steps

J. RESET

If the user requests clearing the current search or session, use action = reset.

==================================================
3. CONVERSATION CONTEXT
==================================================

The conversation state is important.

When the user sends a follow-up:
- Preserve the active dish.
- Preserve existing ingredient requirements.
- Preserve every explicit ingredient/allergy/dietary exclusion until the user removes it or resets the conversation.
- Preserve active search preferences.
- Preserve the previous result session.
- Change only what the user explicitly changes.
- Use the focused recipe and recent user turns supplied in the conversation state to resolve "it", "that recipe",
  "the same dish", and similar references. If no active recipe can be identified, do not invent one.

Examples:

User: "Find chicken recipes."
User: "Without onion."

Keep chicken as the dish and add onion to exclude.

User: "Show me 20 recipes."
User: "More."

Continue the previous list. Do not restart the search.

User: "Find pasta."
User: "Actually, show chicken recipes."

Replace the previous dish with chicken.

A clearly new dish replaces the active dish and result list, but explicit safety/dietary exclusions still apply.
Do not apply the old dish's ingredient requirements to a new dish unless the user asks to keep them.
Only remove exclusions when the user explicitly allows them or resets the session.

Never invent conversation history.

==================================================
4. FIELD RULES
==================================================

dish:
- Actual dish or title search phrase.
- Null for broad database searches.

required_ingredients:
- Ingredients that must be present.

exclude:
- Ingredients that must not be present.

allow:
- Explicitly permitted ingredients when supported by the application.
- Do not use this field to represent an unsupported dietary category.

max_steps:
- Positive integer only when explicitly requested.

top_n:
- Requested result quantity.
- Null when no quantity is specified.
- Never interpret it as a recipe ingredient or keyword.

more:
- True only when continuing an existing result session.
- Otherwise false.

ref:
- Selected recipe ID or reference when available.
- Null when unavailable.

show_parts:
- Only "ingredients" and/or "instructions".

prefer:
- "balanced", "missing", or "steps".
- Default to "balanced".

attribute:
- Short description of an attribute requested by the user.
- Default to "that attribute".

stat:
Use this exact structure:
{
  "type": "count",
  "contains_all": [],
  "contains_any": [],
  "exclude": [],
  "title_words": [],
  "order": "most",
  "n": 5,
  "skip_staples": false
}

have:
Use ingredient objects:
{
  "name": "eggs",
  "qty": null,
  "unit": null
}

substitute:
{
  "target": "butter",
  "recipe": "this",
  "choose": null
}

==================================================
5. IMPORTANT SEARCH RULES
==================================================

- Never search conversational words.
- Never search "top", "best", "show me", or "I want" as literal dish keywords.
- Never convert requested quantities into search terms.
- Never confuse dish names with ingredient restrictions.
- Never silently drop user constraints.
- Never invent ingredients or recipe IDs.
- Never assume a dietary category is supported unless the available application fields can represent it.
- Keep broad discovery searches separate from exact title searches.
- Interpret recipe and ingredient requests neutrally; do not infer quality, healthfulness, cuisine, or user preferences.

==================================================
6. REQUIRED JSON OUTPUT
==================================================

Always return this exact set of keys:

{
  "action": "search",
  "dish": null,
  "required_ingredients": [],
  "exclude": [],
  "allow": [],
  "max_steps": null,
  "top_n": null,
  "more": false,
  "ref": null,
  "show_parts": [],
  "prefer": "balanced",
  "attribute": "that attribute",
  "stat": null,
  "have": [],
  "substitute": null
}

Replace values according to the user's actual request.

Use:
- null for missing or inapplicable values.
- [] for empty lists.
- false for inactive boolean flags.

Return valid JSON only.
Do not use Markdown fences.
Do not explain your decisions.
"""



def _as_list(x):
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    return [str(i) for i in x if i is not None and str(i).strip()] if isinstance(x, list) else []


def _as_int(x):
    try:
        v = int(float(x))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def validate(raw):
    """Coerce an LLM JSON object into a safe plan, or None if unusable."""
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        return None
    p = {"action": raw["action"],
         "dish": (str(raw["dish"]).strip() if raw.get("dish") else None),
         "required": _as_list(raw.get("required_ingredients")),
         "exclude": _as_list(raw.get("exclude")),
         "allow": _as_list(raw.get("allow")),
         "max_steps": _as_int(raw.get("max_steps")),
         "top_n": _as_int(raw.get("top_n")),
         "more": bool(raw.get("more")),
         "ref": (str(raw["ref"]).strip() if raw.get("ref") else None),
         "show_parts": [x for x in _as_list(raw.get("show_parts")) if x in ("ingredients", "instructions")],
         "prefer": raw.get("prefer") if raw.get("prefer") in ("balanced", "missing", "steps") else "balanced",
         "attribute": raw.get("attribute") or "that attribute"}
    st = raw.get("stat")
    if isinstance(st, dict):
        t = st.get("type")
        t = {"avg_ingredients": "ingredient_count_stats", "median_ingredients": "ingredient_count_stats",
             "percentage": "count", "percent": "count"}.get(t, t)
        p["stat"] = {"type": t if t in STAT_TYPES else None, "all": _as_list(st.get("contains_all")),
                     "any": _as_list(st.get("contains_any")), "exclude": _as_list(st.get("exclude")),
                     "title": _as_list(st.get("title_words")), "order": "most" if st.get("order") == "most" else "fewest",
                     "n": _as_int(st.get("n")) or 5, "skip_staples": bool(st.get("skip_staples"))}
    have = []
    for h in raw.get("have") or []:
        if isinstance(h, dict) and h.get("name"):
            q = h.get("qty")
            try:
                q = float(q) if q is not None else None
            except (TypeError, ValueError):
                q = None
            have.append({"name": str(h["name"]), "qty": q, "unit": h.get("unit") or None})
        elif isinstance(h, str):
            have.append({"name": h, "qty": None, "unit": None})
    p["have"] = have
    sub = raw.get("substitute")
    if isinstance(sub, dict) and sub.get("target"):
        p["substitute"] = {"target": str(sub["target"]), "recipe": str(sub.get("recipe") or "this"),
                           "choose": (str(sub["choose"]) if sub.get("choose") else None)}
    if p["action"] == "stats" and not (p.get("stat") and p["stat"]["type"]):
        return None
    if p["action"] == "substitute" and "substitute" not in p:
        return None
    if p["action"] == "match" and not have and "match" not in (raw.get("_ctx") or ""):
        pass      # a match follow-up has no "have": allowed, chat.py checks there is an active match session
    return p


def plan(message, context):
    """-> validated plan dict or None (no LLM / unusable output).  `context` = short text about the session."""
    prompt = f"Conversation state: {context}\nUser message: {message}\nJSON:"
    out = llm.generate(prompt, system=SYSTEM, json_mode=True, timeout=90)
    return validate(parse_json(out))

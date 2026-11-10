# Recipe GenAI Assistant

A conversational chatbot for the [Recipe Box dataset](https://eightportions.com/datasets/Recipes/). It provides a command-line chat and an optional Streamlit UI for searching, analyzing, matching, and adapting recipes. Recipe facts and statistics are grounded in the local dataset; an LLM is optional.

## Features

### Task 1 — Search, Q&A, and statistics

- Search recipes by dish/title and ingredients; return stable IDs and original recipe content.
- Keep an active recipe/search and restrictions across follow-up turns. A new dish replaces the active dish, while explicit restrictions remain until removed or reset.
- Compute counts, percentages, averages, medians, common ingredients, and step rankings in Python/SQLite over the filtered dataset.
- State the filter, analyzed count, denominator, normalization notes, and calculation for statistics.
- Refuse unsupported structured attributes such as nutrition, ratings, servings, and cooking times instead of estimating them.

### Task 2 — Ingredient matching

- Match available ingredients, including optional quantities, to existing recipes.
- Rank eligible recipes with an explainable score; show matches, missing/additional ingredients, and step counts.
- Apply exclusions and step limits as hard constraints. If nothing qualifies, report no match and label any closest constraint-violating alternatives separately.
- Compare quantities only when the units are compatible; otherwise report that only ingredient names were compared.

### Task 3 — Evidence-based substitution

- Adapt an existing recipe using local recipe evidence, including direct ingredient alternatives and evidence from similar recipes.
- Cite supporting recipe IDs; label predictions and indirect or weak evidence.
- Return an updated ingredient list and revised instructions, noting steps that need review and likely trade-offs.
- Do not claim medical/allergen safety. If the local evidence or supported ingredient roles are inadequate, report the limitation rather than inventing a substitute.

## How it works

1. **Ingest:** `recipebot/ingest.py` reads all three JSON files and creates a SQLite database. Original titles, ingredient lists, instructions, and source keys are preserved. IDs use the source prefix and original key (`ar-`, `epi-`, or `fn-`).
2. **Retrieve and compute:** SQLite/FTS proposes search candidates; deterministic code applies recipe filters and restrictions. Statistics are calculated from the complete filtered database set, not just displayed search results. The step-count rule is non-empty instruction lines, or sentences for a single-paragraph instruction.
3. **Match and adapt:** ingredient normalization distinguishes products such as tomato and tomato paste. Matching uses a documented score and hard filters. Substitution responses distinguish local evidence from predictions.
4. **Optional LLM:** the planner emits a structured plan that the application validates and executes; the answer writer is constrained to retrieved data. A grounding check validates numerical values and recipe IDs. If no LLM is available, the rule-based path remains usable.

Restrictions are checked against recipe ingredient text and cannot reveal undeclared ingredients or guarantee allergy safety. See **Limitations** below.

## Run locally (Windows PowerShell)

### 1. Get the code and install the UI dependency

Clone your GitHub repository, then from its folder run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use the virtual-environment interpreter directly, for example `.\.venv\Scripts\python.exe`.

### 2. Add the dataset and build the database

Download the three JSON files from the dataset page and place them in `data\`:

```text
data\recipes_raw_nosource_ar.json
data\recipes_raw_nosource_epi.json
data\recipes_raw_nosource_fn.json
```

Create `data\` first if it does not exist:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
```

Then ingest them once:

```powershell
python -m recipebot.ingest --data-dir data --db data/recipes.db
```

The raw dataset and generated database are ignored by Git; do not commit them unless you have confirmed redistribution is permitted.

### 3. Start chatting

Rule-based CLI (no LLM setup required):

```powershell
python -m recipebot.chat --db data/recipes.db --no-llm
```

Optional Streamlit web interface:

```powershell
python -m streamlit run app.py
```

The app opens in a browser. Use **New conversation** to clear its session. To run the CLI with automatic optional LLM selection, omit `--no-llm`. Ollama is tried first; Gemini can be used as a fallback.

Optional LLM configuration:

```powershell
# Ollama: install Ollama, then pull a supported model
ollama pull qwen2.5:7b
$env:OLLAMA_MODEL = "qwen2.5:7b"

# Or use Google AI Studio
$env:GEMINI_API_KEY = "your-key"
$env:LLM_PROVIDER = "gemini"
```

Set `LLM_PROVIDER` to `none` to disable LLM calls. Do not commit API keys.

## Example conversation

```text
Find a penne pasta recipe.
I cannot have dairy.
Show #1

How many recipes contain both garlic and onion? What percentage of the dataset is that?
Among recipes containing tomato, which five have the fewest instruction steps?

I have eggs, onions, tomatoes, and rice. Suggest five recipes, no peanuts,
at most six steps. Prefer recipes that need the fewest additional ingredients.
Exclude eggs too.

Take the banana bread recipe and remove eggs. Use only ingredients that appear in the dataset.
```

In dish searches, a plain “with” may be part of the dish title. Specify required ingredients explicitly, such as “pasta containing garlic” or “penne with ingredients spinach.” In statistics questions, “recipes with tomato” is treated as an ingredient filter.

## Tests and evaluation

Run the unit tests:

```powershell
python -m unittest discover -s tests
```

Run the reproducible 20-case evaluation against the bundled small fixture:

```powershell
python eval/run_eval.py
```

The evaluation uses an independent, simple oracle over the fixture JSON and covers follow-up restrictions, aggregate statistics, rankings, no-match behavior, matching constraints, quantities, substitution evidence, and normalization edge cases. Results are written to `eval/results.md`. The checked-in result file records **20/20 passed on the bundled fixture**; run the command above to reproduce it.

To evaluate against the downloaded dataset:

```powershell
python eval/run_eval.py --data-dir data --db data/recipes.db
```

The simple oracle may disagree with the more conservative normalizer on distinctions such as tomato versus tomato sauce; inspect differences rather than treating every discrepancy as a chatbot defect. `tests/test_llm_layer.py` uses a stub provider to verify that unsupported/hallucinated values are rejected. An optional one-shot comparison is available in `eval/oneshot_baseline.py`; it requires a configured LLM provider.

## Design choices

- **Stable source IDs:** IDs retain the source (`ar`, `epi`, or `fn`) and original dataset key.
- **Preserved records:** original title, ingredient list, and instructions remain available alongside normalized fields.
- **Normalization:** ingredient parsing uses whole-word rules and a synonym lexicon; distinct products remain distinct when that affects matching.
- **Statistics:** SQL/Python calculates the complete filtered population, denominator, and ranking values. No LLM performs arithmetic.
- **Hard constraints:** exclusions and step limits filter results; they are not soft ranking penalties and are not silently relaxed.
- **Matching score:** `100 × (wᵣ × recall + w꜀ × coverage + wₛ × step_ease)`. The selected preference determines weights; ties use fewer missing ingredients, fewer steps, then recipe ID. Salt, water, and black pepper are assumed available and are disclosed in the output.
- **External search:** not used. Substitution evidence comes from the local recipe collection.

## Limitations

- Dataset fields do not provide reliable nutrition, ratings, serving counts, or structured cooking times. Times found in instruction text are not equivalent to verified cooking-time metadata.


## AI tool disclosure

I have used **Claude and GitHub Copilot** during development, mainly for analysing data, exploring system design decisions, and evaluating the overall architecture.

One approach I found particularly useful was using them as independent reviewers. I would share my initial idea or architecture with both tools, compare their suggestions, and make them challenge each other's approaches by examining the pros, cons, trade-offs, and possible limitations.

This helped me identify design gaps, explore alternative solutions, and make the architecture more efficient and reliable.

However, I don't blindly accept AI-generated suggestions. I evaluate them against the actual project requirements, implement the decisions myself, and make sure I understand the underlying logic, code, and trade-offs. I can also explain and modify the implementation without depending on these tools.

## Publish this project to GitHub

1. Create a **public, empty** repository on GitHub (do not initialize it with another README or license).
2. From the project folder, initialize Git and stage only source, tests, evaluation files, and documentation. Do not stage the dataset, database, virtual environment, or API keys:

```powershell
git init -b main
git status --short
git add README.md .gitignore app.py requirements.txt recipebot tests eval .streamlit
git status --short
git commit -m "Prepare recipe assistant assignment"
```

3. Replace `<USERNAME>` and `<REPOSITORY>` below with the GitHub account and repository name, then connect and push:

```powershell
git remote add origin https://github.com/<USERNAME>/<REPOSITORY>.git
git push -u origin main
```

Authenticate with Git Credential Manager or `gh auth login` when prompted. Never put a personal access token or API key in the remote URL or in a committed file. If `git status --short` lists a dataset, database, `.venv`, or secret file, stop and fix `.gitignore` before staging or pushing.

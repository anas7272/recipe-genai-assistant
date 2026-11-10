# Evaluation results (20/20 passed)

Data: `tests/fixture` (30 unique valid recipes). Oracle = plain regex over raw JSON, independent of the bot's parser.

| # | check | result |
|---|---|---|
| 1 | T1 follow-up: dairy restriction refines the active penne search (complete + sound vs oracle) | PASS |
| 2 | T1 evidence: exempted 'coconut milk' is explained, not silently accepted | PASS |
| 3 | T1 restriction persists when the dish changes | PASS |
| 4 | T1 aggregate: count garlic AND onion equals oracle | PASS |
| 5 | T1 aggregate states filter, N analysed, denominator and normalisation | PASS |
| 6 | T1 ranking: five fewest-step tomato recipes equal oracle (ties by ID) | PASS |
| 7 | T1 median ingredient count equals oracle | PASS |
| 8 | T1 refuses attributes the data lacks (nutrition / cooking time) instead of estimating | PASS |
| 9 | T2 hard constraints: every result has <=6 steps and no peanut | PASS |
| 10 | T2 output shows matched / missing / why for each result | PASS |
| 11 | T2 follow-up 'Exclude eggs too' removes every egg recipe (oracle check, incl. whole-word 'egg') | PASS |
| 12 | T2 no-match case: says no match, flags violators, never presents them as eligible | PASS |
| 13 | T2 quantities: compared when units are comparable, else reported as name-level | PASS |
| 14 | T3 cites local recipe IDs as evidence and labels predictions | PASS |
| 15 | T3 returns an updated ingredient list AND revised instructions, no eggs left | PASS |
| 16 | T3 weak evidence is flagged (flaxseed has no similar-recipe support in the sample) | PASS |
| 17 | T3 reports remaining dairy (butter/parmesan) after replacing cream - no false 'safe' claim | PASS |
| 18 | T3 refuses an ingredient it has no role knowledge for rather than inventing a substitute | PASS |
| 19 | Ingest: uses all three files; raw = valid + invalid; unique = oracle count | PASS |
| 20 | Normalisation traps: 'egg' not matched inside eggplant/Reggiano/veggie, but matched in 'eggs' | PASS |

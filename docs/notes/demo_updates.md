# Demo updates: AI search retrieval

## Changes

- **Embedding retrieval:** listings are ranked by MiniLM similarity plus a keyword bonus, and the top 15 go to the model (was 40). If MiniLM can't load, search falls back to keywords.
- **Semantic gate:** a pick is kept if it shares a query concept _or_ has similarity ≥ 0.35.
- **Keyword expansion:** a word with no matches is widened to its synonyms (e.g. "decorate" → rug, lamp, vase).
- **Parsing:** `[{"ids":[...]}]` responses are now accepted.

## Results

Evaluation (`evaluate_ai`, 40 listings, 8 gold queries):

|                    | Before | After |
| ------------------ | ------ | ----- |
| NDCG@5             | 0.574  | 0.660 |
| Recall@5           | 0.504  | 0.662 |
| Median search time | 7.6 s  | 3.6 s |

Development database:

| Query               | Before            | After                                 |
| ------------------- | ----------------- | ------------------------------------- |
| decorate my room    | 5 newest listings | Pillow, wall art, curtains, rug, lamp |
| something to sit on | No results        | Sectional sofa                        |
| keep my food warm   | No results        | Microwave                             |
| bathroom cleaning   | No results        | No results (correct)                  |

**Where the gain comes from:**

- On the evaluation set, mostly the gate. With the new pool alone, NDCG@5 stayed at 0.573. That set has only 40 listings, so the old pool already included all of them.
- On the development database, the new pool is what gives the model relevant items to pick.

## Limitations

- The 0.35 threshold was tuned on a small set. Re-check it with `evaluate_ai` as listings grow.
- MiniLM scores are close together. For "sit", the loveseat (0.34) is just below the threshold.
- The keyword side of the gate is loose. "coffee table" can still show a desk lamp.
- Setup: run `pip install -r requirements.txt` to get `sentence-transformers`.

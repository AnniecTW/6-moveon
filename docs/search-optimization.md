# Natural-language listing search optimization

The current search path applies the existing active-listing and structured
filters in the database, embeds each eligible listing's title, category, and
description with `sentence-transformers/all-MiniLM-L6-v2`, and ranks by cosine
similarity to the buyer's query. Listing fields are separated into short
sentences. The highest scoring eight listings above a 0.30 retrieval threshold reach the original
`meta-llama/Llama-3.2-3B-Instruct` model for final ordering. Llama sees short
listing fields and can return at most five IDs. Django checks ID membership,
removes duplicates, and rechecks active status and filters before display.
The restored relevance gate also requires at least one query concept to appear
in the listing's title, category, or description. It ignores filler words and
uses synonym groups, including seating terms for "sit"; it does not require
every word in a natural-language query to match. The same gate applies to
semantic fallback results so rejected listings cannot reappear through fallback.
This lexical safeguard can miss paraphrases outside its synonym groups and
does not guarantee that a listing satisfies every part of the shopper's intent.
The retrieval stage scans at most 1,000 eligible listings; above that limit
search reports unavailable rather than silently excluding older inventory.

Llama failure, malformed JSON, invalid IDs, or an empty Llama result shows up
to five semantic matches scoring at least 0.40, explicitly labeled as a
fallback. With no sufficiently strong match the page shows an empty or
unavailable state. Embedding, database,
or catalog-size failure shows an unavailable message. Random listings are
never presented as recommendations. The pricing feature's MiniLM loader is
reused. Retrieval and fallback have separate cutoffs because the latter has
no Llama check before display.

## Evidence and current limits

The saved A9 baseline in
[`results_after_repeat.json`](A9-part3/results_after_repeat.json) measured the
earlier lexical pipeline on an Apple M4 with 40 listings: 0.454 mean nDCG@5,
0.360 mean Recall@5 over eight gold queries, two fallbacks over ten queries,
7.97 s median generation, and 7.98 s median request time. The original
Windows CPU report was over seven minutes for some requests; it was not
instrumented here and is not a directly comparable benchmark. The older
[`results_before.json`](A9-part3/results_before.json) captures the stricter
lexical gate, where all ten queries fell back. These reports diagnose the
gate and fallback behavior, but they do not establish improvement for this
implementation.

MiniLM weights are now cached locally. On the 43-active-listing development
catalogue, the exact query "I need something to heat up food quickly."
previously scored 0.358 for the top microwave using concatenated fields, below
the former 0.40 cutoff. With sentence-separated fields it scores 0.430 for
`Microwave` and 0.413 for `Countertop Microwave`, and both enter the Llama
shortlist. A 17-query A6 catalogue retrieval probe showed that lowering the
cutoff to 0.30 raises relevant-item candidate recall from 0.488 to 0.767
with sentence-separated fields. The probe also produced more irrelevant raw
candidates, so these numbers **do not establish end-to-end quality**; Llama
ranking and its failures must be measured separately. The optimized pipeline
still has **no measured end-to-end quality or CPU latency result**. The 0.30
retrieval cutoff, 0.40 fallback cutoff, and eight-candidate rerank size are
starting values, not guarantees. They should be selected with held-out
labels before deployment. The `max_time=60` Transformers setting starts
after model loading and prompt preparation and is checked when generation
returns; it is not a hard HTTP request deadline. CPU prompt processing and
model loading can still be slow.

## Reproduce the evaluation

Use a separate empty database and a machine with both model weights available:

```powershell
$env:DATABASE_PATH = 'data/eval-search.sqlite3'
python manage.py migrate
python manage.py sync_pricing_taxonomy
python manage.py evaluate_ai --seed --skip-pricing --label semantic-search
```

The command evaluates the original eight A6 gold queries plus nine additional
cases covering appliance use, room context, furniture, electronics, decor,
budget, multiple attributes, and absent inventory. The additional cases
include paraphrases and previously unused requests. Each case records
retrieved IDs and cosine scores, raw Llama IDs, displayed IDs, retrieval,
generation, and request time, nDCG@5, Recall@5 where labels exist,
Precision@5 over displayed results, and false-positive count against the
labels. Reported cosine scores are rounded to one decimal place; ranking and
cutoff checks use the unrounded scores. Compare the generated
`docs/A9-part3/results_semantic-search.json` with the saved baseline only
after accounting for hardware, model cache state, and the expanded query set.
Run repeat trials, inspect every false positive and false negative, then
choose the cutoff and rerank size on a separate held-out set. No examples in
the evaluation set should be treated as proof of general search quality.

Model-load and prompt-tokenization timings are logged by `marketplace.local_llm`.
It also logs time to first token, which includes model prompt processing and
first-token generation, then time for remaining tokens. The command reports
model load and retrieval separately, plus total inference and request time.
A real server deployment still needs a
request-level deadline and worker isolation for strict latency bounds.

Validation in this workspace: `python manage.py check` and
`python manage.py test tests.marketplace.test_local_llm_search --keepdb`
passed (11 cases) using a controlled encoder and mocked Llama output. Those tests cover
semantic ranking, ID validation, structured filtering, empty results, and
labeled fallback; they are not evidence of real-model quality.
The full Django suite ran 285 tests and failed in the unrelated PNG worker
timeout cleanup test (`test_actual_30_second_worker_timeout_kills_a_live_relay_and_stalled_descendant`).
The same test failed when run alone; its child process remained running after
the test deadline. No PNG subprocess code was changed here.

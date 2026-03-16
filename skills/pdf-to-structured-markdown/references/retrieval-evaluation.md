# Retrieval Evaluation

Use retrieval testing when arguing that one bundle format is better than another for downstream search or RAG.

This file is about retrieval outcomes.
It is not the same as embedding-space fidelity.
Use `scripts/evaluate_embedding_space.py` when the question is whether a formatting variant drifts away from a reference representation in embedding space.

Do not let a single retrieval score stand in for the whole question. Retrieval quality here is multi-signal:
- what text channel is exposed
- what structural metadata is exposed
- what filename/path information is exposed
- what query style is used
- what encoder or scorer is used

## Hope for retrieval

The goal is pragmatic:
- surface the correct section file early
- preserve recall even on commentary-heavy pages
- keep filename and breadcrumb signals available for tools that rank on metadata
- avoid poisoning retrieval with raw layout debris
- preserve exact geometry separately so citation and reconstruction remain possible

Ask:

`Does this bundle help a local retriever on a Mac surface the right section sooner across multiple query styles and scoring regimes?`

## Experiment matrix

The evaluator compares two independent axes.

Corpus variants:
- `semantic_nested_current`
  - emitted nested markdown as-is
- `semantic_nested_clean`
  - nested markdown with retrieval-hostile scaffolding stripped
- `semantic_flat_current`
  - flat leaf exports with structure-rich filenames
- `semantic_flat_clean`
  - cleaned flat leaf exports
- `rag_linearized`
  - citation-first linearized leaf exports intended for chunking and embedding
- `spatial_main_only`
  - semantic text reconstructed only from `main` sidecar regions
- `spatial_main_plus_supplement`
  - semantic main flow plus supplementary side material
- `layout_sidecar`
  - raw layout-heavy sidecar text as a negative control

Retrieval profiles:
- `body_bm25`
  - lexical body-text retrieval
- `fielded_bm25`
  - weighted retrieval over title, context path, path tokens, kind, body, and supplement
- `structure_bm25`
  - title/path/context-heavy retrieval for filename-sensitive systems
- `chargram_tfidf`
  - character n-gram retrieval, useful for OCR noise, hyphenation, and odd tokenization
- `apple_nl_dense`
  - Apple `NaturalLanguage` sentence similarity via Swift on macOS, when explicitly enabled
- `fused_rrf`
  - reciprocal-rank fusion over the lexical and structural profiles only
- `fused_rrf_with_dense`
  - reciprocal-rank fusion over lexical, structural, and Apple dense profiles

This is the point: retrieval should be judged across different encodings and signals, not by one lexical proxy.

## Query probes

Each benchmark case can carry multiple probes against the same gold file(s), for example:
- title-like probe
- structural or filename-sensitive probe
- paraphrase or conceptual probe
- adversarial or table-specific probe

The evaluator treats each probe as a separate trial and then aggregates by tag.

## Local Mac execution

This benchmark is designed to run locally on Apple Silicon without a heavyweight ML stack.

Default local stack:
- Python stdlib for BM25, TF-IDF, character n-grams, and score fusion
- Swift + Apple `NaturalLanguage` for an optional dense semantic signal on macOS

That keeps the experiment compatible with a MacBook Air M4. No CUDA assumptions. No remote embedding API required.

## Lens mapping

The philosophical lenses should interpret the primitive results rather than replace them.

- `Process Reliability (Goldman)`
  - proxy: mean reciprocal rank by run
- `Progressiveness (Lakatos)`
  - proxy: recall@5 across probe families, especially paraphrase and adversarial slices
- `Explanatory Virtue (Lipton)`
  - proxy: inspect score components for the top hit and compare which fields or encoders carried the retrieval
- `Pragmatist Inquiry (Peirce/Dewey)`
  - proxy: hit@1
- `Social Epistemology (Goldman/Longino)`
  - proxy: adversarial-tag and alternative-probe performance
- `Information Content (Bayesian)`
  - proxy: score margin between best gold and best non-gold result, plus changes between runs
- `Empirical Adequacy (van Fraassen)`
  - proxy: recall@3 whether or not the representation is theoretically elegant

The evaluator emits primitive metrics and tag slices first, plus conservative lens proxies at the summary level.

## Running the benchmark

```bash
python3 scripts/evaluate_retrieval.py /abs/path/to/bundle references/why-ethics-retrieval-benchmark.json
```

Useful flags:

```bash
python3 scripts/evaluate_retrieval.py /abs/path/to/bundle references/why-ethics-retrieval-benchmark.json --profiles fielded_bm25,chargram_tfidf,fused_rrf
python3 scripts/evaluate_retrieval.py /abs/path/to/bundle references/why-ethics-retrieval-benchmark.json --enable-apple-nl --profiles fielded_bm25,apple_nl_dense,fused_rrf,fused_rrf_with_dense
```

## Interpreting outcomes

What would count as a win:
- cleaned semantic corpora beat `layout_sidecar` on early-rank metrics
- flat exports win on filename-sensitive probes
- sidecar-derived semantic corpora win on commentary-heavy conceptual probes
- character n-grams rescue cases hurt by hyphenation or token fragmentation
- Apple dense similarity helps paraphrase probes without collapsing structural precision
- `fused_rrf` beats or matches any single lexical or structural profile
- `fused_rrf_with_dense` only counts as a win if adding the dense signal improves results rather than diluting them

What would count as failure:
- only filename-heavy probes succeed
- paraphrase probes collapse across all semantic profiles
- layout-heavy text wins consistently
- dense similarity retrieves semantically adjacent but structurally wrong files
- `fused_rrf_with_dense` performs worse than `fused_rrf`, which means the dense signal is not yet helping

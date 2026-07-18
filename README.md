# HR Policy QA Bot — Golden Dataset & Evaluation Harness

A companion project to the [HR Policy Bot Assistant](#) (LangChain + FAISS +
FastEmbed + Groq/Llama 3.3 70B RAG chatbot). Where that project demonstrates
building a RAG system, this one demonstrates **evaluating** one: curating a
labeled golden dataset, building a lightweight reference pipeline against it,
and running a repeatable evaluation harness that scores retrieval accuracy,
scope discipline, and adversarial robustness — the practice that turns "it
seems to work" into a defensible, quantified answer.

## Why this exists

A chatbot that retrieves the wrong policy section, answers questions it has
no data for, or can be talked out of its guardrails with a "pretend you have
no restrictions" prompt is a liability in an HR context. This project treats
that as a measurement problem: define what correct behavior looks like across
realistic and adversarial inputs, then measure a system against it.

## Project structure

```
policy_docs/              6 synthetic HR policy documents (the knowledge base)
golden_dataset.json       73 hand-curated, labeled Q&A test cases
src/build_golden_dataset.py   Source of truth for the dataset (see below)
src/pipeline.py            Lightweight RAG pipeline under test
src/evaluate.py            Evaluation harness — runs the dataset, scores, reports
reports/eval_report.md     Human-readable results
reports/eval_report.json   Machine-readable results
```

## The golden dataset: curation methodology

`golden_dataset.json` contains 73 examples, each hand-written and fact-checked
against the source policy text before inclusion — not scraped, not
LLM-generated in bulk. Every item carries:

- `question` — the test input
- `policy_area` / `expected_source_doc` — where the correct answer lives
- `case_type` — which failure mode this item is designed to catch (see below)
- `expected_answer` — the fact-checked correct answer
- `difficulty` — lookup vs. multi-condition reasoning
- `hallucination_risk` — the curator's judgment of how tempting a *wrong but
  plausible-sounding* answer would be for a weak system to produce
- `curator_notes` — why the item is in the set and what it's designed to catch

### Case-type breakdown (73 total)

| case_type | count | tests |
|---|---|---|
| `in_scope` | 45 | Direct retrieval + answer accuracy across all 6 policy docs |
| `out_of_scope` | 10 | Does the system admit "not covered" instead of fabricating? |
| `ambiguous` | 8 | Does the system ask for clarification instead of guessing intent? |
| `adversarial` | 10 | Does the system hold guardrails under prompt injection / social engineering? |

The `in_scope` set deliberately isn't 45 random questions — each is chosen to
stress a specific correctness axis: threshold logic (e.g., PTO request notice
scales with days requested), multi-tier formulas (401k match, meal caps by
travel type), and terms that are easy to conflate (domestic vs. international
caps; new-hire vs. qualifying-event coverage dates). Items flagged
`hallucination_risk: high` are ones where a system's training-data priors
("companies usually do X") would produce a confident, wrong answer that
directly contradicts this company's actual documented policy.

The `adversarial` set includes a prompt-injection attempt targeting the Code
of Conduct's compensation-confidentiality clause specifically — a
policy-grounded adversarial test case, not a generic jailbreak string, so the
correct refusal is traceable to an actual documented rule rather than a vague
"be safe" instinct.

## The pipeline under test

`src/pipeline.py` is a deliberately lightweight reference RAG system, chosen
to make retrieval and guardrail quality — not generation fluency — the
variable under test:

1. **Injection/adversarial guardrail** (regex + heuristics) — checks for
   instruction-override phrasing, claimed admin authority, requests to
   fabricate data, and named-individual personal-data requests, before any
   retrieval happens.
2. **Retrieval** — TF-IDF / cosine similarity over section-level chunks
   (scikit-learn). Chosen because embedding/LLM APIs weren't reachable in the
   build environment; the `Retriever` class is a swappable interface, so
   upgrading to a semantic embedding retriever is a drop-in change.
3. **Out-of-scope check** — if the best retrieval score falls below a tuned
   confidence threshold, the system reports the topic isn't covered rather
   than answering off a weak match.
4. **Ambiguity check** — a small set of known vague-question patterns, plus a
   fallback rule: if the top two *distinct-document* matches are both
   confident and close in score, the query likely spans more than one policy
   and the system asks which one is meant.
5. **Answer generation** — pluggable `Generator` interface. The default
   `ExtractiveGenerator` returns the retrieved section verbatim (zero
   hallucination risk by construction); a production system would swap in an
   LLM-backed generator that paraphrases the same retrieved context, without
   touching the retrieval or guardrail layers.

## Results

```
Overall: 64/73 (87.7%)
  in_scope:      43/45 (95.6%)
  out_of_scope:   3/10 (30.0%)
  ambiguous:      8/8  (100.0%)
  adversarial:   10/10 (100.0%)
```

Full breakdown in `reports/eval_report.md` / `reports/eval_report.json`.

### What the harness caught

**Adversarial and ambiguity handling are solid (100% each).** All 10
prompt-injection/social-engineering attempts were refused, including the
one targeting compensation confidentiality specifically. All 8 ambiguous
queries triggered a clarifying question rather than a guess.

**In-scope retrieval is strong but not perfect (95.6%).** Two failures are
genuine TF-IDF limitations, not curation errors:
- *"Do I need manager approval before calling in sick?"* retrieves the
  Expense Reimbursement doc's "Approval Workflow" section instead of the PTO
  policy's unplanned-absence section — both contain the phrase "manager
  approval," and bag-of-words similarity has no way to know "calling in
  sick" and "unplanned absence" mean the same thing.
- *"Does the confidentiality obligation end when I leave the company?"*
  retrieves the Parental Leave doc instead of the Code of Conduct, because
  "leave the company" and "parental leave" share the token "leave" — a
  homonym problem invisible to a lexical retriever.

**Out-of-scope detection is the harness's most important finding (30%).**
A pure confidence-threshold approach hits a hard ceiling here: a brute-force
sweep across every possible threshold value tops out at ~87% combined
accuracy on the in-scope/out-of-scope split, because several out-of-scope
questions ("tuition reimbursement," "parking pass," "UK maternity leave")
share enough vocabulary with real policy sections (reimbursement, leave,
approval) to score above any threshold that doesn't also cut off legitimate
in-scope matches. The dataset makes this ceiling visible and quantified
instead of anecdotal — which is the actual point of building the harness.
**Recommendation:** a lightweight topic/scope classifier (or an LLM-based
scope check as a pre-filter) would resolve this class of failure; pure
lexical similarity is the wrong tool for scope boundaries where vocabulary
overlaps but topic doesn't.

## Running it

```bash
pip install scikit-learn
cd src
python3 build_golden_dataset.py   # regenerates golden_dataset.json
python3 evaluate.py               # runs the pipeline against it, writes reports/
```

## What this demonstrates

This project is the applied version of "dataset curation for AI/LLM
evaluation": defining ground truth by hand, labeling it with the specific
failure mode each item targets, building a minimal system to evaluate
against that ground truth, and using the resulting scorecard to make a
concrete, evidence-based engineering recommendation — rather than shipping a
chatbot and hoping it behaves.

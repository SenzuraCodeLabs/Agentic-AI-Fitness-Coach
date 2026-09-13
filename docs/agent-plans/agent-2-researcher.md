# Agent 2: Researcher and evidence quality

Owns `services/agent2_researcher/`. Supplies relevant, attributed evidence; it does not calculate loads or make model calls for embeddings. All-MiniLM-L6-v2 runs locally and Chroma persists vectors.

## Implemented in this improvement

Corpus grows from 20 to 26 passages with six linked references. A content fingerprint refreshes changed corpus entries, including existing databases. Retrieval fetches a broader candidate set, blends vector similarity with topic/term overlap, filters weak results and removes repeated sources and near-identical text. The async endpoint runs blocking retrieval in a worker thread. Links and full curated snippets propagate to the coach.

New linked references: [ACSM progression](https://pubmed.ncbi.nlm.nih.gov/19204579/), [CDC activity](https://www.cdc.gov/physical-activity-basics/guidelines/adults.html), [elastic resistance](https://pubmed.ncbi.nlm.nih.gov/30815258/), [training to failure](https://pubmed.ncbi.nlm.nih.gov/33497853/), [CDC sleep](https://www.cdc.gov/sleep/about/), [RIR estimation accuracy](https://pubmed.ncbi.nlm.nih.gov/34542869/).

## What to explain at the viva

Nearest neighbours are not automatically relevant. Candidate retrieval, reranking, an evidence threshold and deduplication are separate steps. Scores are ranking heuristics, not factual correctness probabilities. Returning fewer sources is better than filling every slot with irrelevant material. Reusing a source across related questions is valid; repeating it within one result is unnecessary.

## Next bounded work

1. Verify each original attribution, add a precise URL/DOI/edition and label practical heuristics separately from research findings.
2. Build a document ingestion command with provenance, reviewed dates and chunk-level identifiers; avoid scraping arbitrary untrusted pages into the live corpus.
3. Label topic-diverse queries and report Recall@k, MRR, source precision and duplicate rate. Tune the local-answer threshold against answer coverage, not only nearest-neighbour distance.
4. Add a full update/restart test proving content refresh and imported-document preservation.
5. Evaluate compound questions and contradictory evidence; abstain when one matching passage covers only part of a request.

## Follow-up prompt

> Read docs/improvement-plan.md and the Researcher code. Audit the original 20 corpus passages against primary sources and replace unsupported or overly strong claims with sourced, conservative summaries. Preserve IDs where possible and add provenance. Create a held-out retrieval evaluation with relevant IDs and rejection cases. Keep retrieval and embeddings local. Verify persistent index updates, no duplicate sources, and no irrelevant citations. Report coverage limits instead of claiming the corpus is comprehensive.

Acceptance: protein, sleep, technique, volume and plateau questions produce topic-appropriate results; empty/off-topic input does not fill the panel; duplicates are removed; restarting after a corpus edit refreshes content.

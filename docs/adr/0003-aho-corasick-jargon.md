# ADR 0003: Aho-Corasick for jargon expansion

**Status:** Accepted, 2026-09-09

## Context

L3 maps 619 gym-jargon variants onto 184 standardised terms. The obvious
implementation loops over the dictionary calling `str.replace`.

## Decision

Build one Aho-Corasick automaton at module load and match in a single pass.

## Rationale

The naive loop is O(n x m): each of m patterns rescans the whole n-character
input, so a 200-character message is scanned 619 times.

Aho-Corasick builds a trie of all patterns with failure links, then matches in
O(n + z) where z is the number of matches, independent of dictionary size.
Construction is O(total pattern length), paid once per process, which is why
the automaton is cached with `lru_cache`.

Correctness matters more than speed here. The naive loop is order-dependent:
an earlier replacement creates or destroys later matches. Measured directly,
`"bench"` becomes `"barbell barbell bench personal recordess"` under the loop,
because "bench" expands, then "bar" and "pr" fire inside the result. The
automaton finds all matches against the original text, and a leftmost-longest
pass resolves overlaps deterministically.

Measured at 619 patterns on a 182-character input, the full layer including
fuzzy matching runs at p95 = 0.39ms against a 15ms budget.

## Consequences

- Matching cost is independent of dictionary growth.
- The automaton must be cached; rebuilding per request would make it slower
  than the loop it replaces.
- Overlap resolution is explicit code, not a side effect of iteration order.

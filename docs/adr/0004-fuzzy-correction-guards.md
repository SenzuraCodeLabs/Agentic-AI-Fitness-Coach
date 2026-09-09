# ADR 0004: Constrain fuzzy jargon correction

**Status:** Accepted, 2026-09-09

## Context

L3 corrects misspelled gym terms with rapidfuzz. The first implementation used
`fuzz.WRatio` against the whole vocabulary above a threshold of 88.

## Problem observed

It corrupted ordinary text. Measured during development:

| Input word | Wrongly corrected to | Score |
| --- | --- | --- |
| `week` | deload | 90 |
| `sore` | delayed onset muscle soreness | 90 |
| `might` | hip thrust | 90 |
| `some` | isometric | 90 |

`WRatio` rewards partial substring overlap, so a short common English word
scores highly against a long multi-word phrase containing a similar fragment.

## Decision

Three guards:

1. **`fuzz.ratio` instead of `WRatio`.** Plain Levenshtein ratio compares whole
   strings, which is the actual question being asked: is this a misspelling of
   that?
2. **A stoplist** of ordinary English words that are never gym jargon.
3. **A length-ratio guard** of 0.6 to 1.6. A real typo is close in length to
   its target; a 4-character token is not a misspelling of a 28-character
   phrase.

## Rationale

A wrong correction silently rewrites what the user said, which is worse than
leaving an unknown token for the extractor to handle. Genuine typos are still
caught: "dealift" scores 93 and "squts" scores 91.

## Consequences

- Recall on unusual misspellings drops slightly; precision rises sharply.
- The stoplist is maintenance the OOV candidates file helps inform.

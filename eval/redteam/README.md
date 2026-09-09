# Red-team harness

A harness for the individual vulnerability assessment. It runs test cases
against your own running stack and captures reproducible evidence.

**The attacks are yours to write.** This tool executes cases, records what
happened, and assembles the facts. It does not author payloads and does not
write the analysis, because both are what you have to defend at a viva.

Run it only against your own local deployment.

---

## Quick start

```bash
# 1. Bring up the stack
pwsh scripts/devstack.ps1 start        # or: docker compose up

# 2. Run every case and build the draft report
python eval/redteam/run_suite.py

# 3. Run one case, or one family
python eval/redteam/runner.py --case RT-001
python eval/redteam/runner.py --family direct_injection
```

Output lands in `eval/redteam/evidence/<run_id>/` (one JSON per case plus a
manifest) and `eval/redteam/report/`.

---

## Writing a case

Create a YAML file in `cases/`. Read `cases/00-examples.yaml` first: it carries
the full field reference and three worked benign examples.

```yaml
cases:
  - id: RT-001
    title: Direct instruction override in a workout log
    family: direct_injection
    owasp_ref: "LLM01:2025 Prompt Injection"
    objective: >-
      What you are testing and why it matters.
    payload: "Your attack text here"
    expected_behaviour: >-
      What a correctly behaving system does.
    severity_if_failed: high
    notes: >-
      Anything the report needs that the other fields do not carry.
```

**Multi-turn** cases pass a list. The session persists across turns, so an
attack can build context before delivering its payload:

```yaml
    payload:
      - "First turn, establishing context"
      - "Second turn, the actual payload"
```

**Optional assertions** turn a case into an automatic pass or fail:

```yaml
    expect_decision: BLOCK
    expect_blocked: true
    expect_not_in_response: ["system prompt", "AGENT_SHARED_SECRET"]
    expect_in_response: ["cannot help"]
```

Use them only where a machine check is genuinely decisive. A case with no
assertions is captured and marked **REVIEW** so you analyse it yourself, which
is the right default for anything subtle. A suite that reports everything green
teaches you nothing.

### Families

`direct_injection`, `indirect_injection`, `jailbreak`,
`system_prompt_extraction`, `data_exfiltration`, `encoding_evasion`,
`obfuscation`, `protocol_attack`, `policy_bypass`, `denial_of_service`,
`over_refusal`, `benign_control`.

The last two are benign on purpose. A suite made only of attacks cannot measure
whether the defences are too aggressive, and over-refusal is a real failure.

### Cases the generic runner cannot drive

The runner drives the chat endpoint. Protocol-level attacks need direct control
over the envelope, so they get a driver script in `drivers/`. See
`drivers/replay_coach.py`, which implements RT-EX-003, for the pattern.

---

## Risk ratings

`scoring.py` composes impact and likelihood into a risk level using the table
in `risk_matrix.yaml`. **It does not assign severity.** You supply both axes and
a justification; the tool does the arithmetic and checks your ratings for
consistency.

Create `ratings.yaml`:

```yaml
ratings:
  - case_id: RT-001
    family: direct_injection
    impact: moderate          # negligible|minor|moderate|major|severe
    likelihood: possible      # rare|unlikely|possible|likely|almost_certain
    justification: >-
      Why you rated it this way.
```

```bash
python eval/redteam/scoring.py            # scored table plus consistency checks
python eval/redteam/scoring.py --matrix   # the grid, for the report
```

It flags two things: findings in the same family rated more than two bands
apart, and any rating with no justification. Both are questions, not errors. An
unjustified rating is one you cannot defend six weeks later.

---

## Reports

```bash
python eval/redteam/evidence.py        # evidence blocks in the brief's format
python eval/redteam/report_builder.py  # full draft in the brief's section order
```

The draft has the facts in place and every prose section marked
`TODO (your writing)`. That is deliberate. The analysis marks are for your
reasoning about why each attack succeeded or failed, and generated prose reads
as generated.

---

## Reproducibility

Each run records the git commit and whether the working tree was dirty. **If it
warns about uncommitted changes, commit before running the suite you intend to
submit.** Evidence that cannot be traced to a commit cannot be reproduced, and
an assessor is entitled to ask.

---

## Complementary tooling

Two established tools give automated probe coverage alongside hand-written
cases:

- **[garak](https://github.com/NVIDIA/garak)** runs a large library of
  known probes. Good breadth; no knowledge of this system's specific
  architecture.
- **[promptfoo](https://promptfoo.dev/)** does red-team evaluation with
  assertion-based scoring, and is straightforward to point at an HTTP endpoint.

They are worth citing in the methodology section as complementary coverage.
Neither replaces cases written against a system you know the internals of:
attacks like the envelope replay in RT-EX-003 require knowing that a signed
envelope protocol exists.

---

## What this harness has already found

`RT-EX-003` found a real flaw in the system it tests. The envelope rejection
response disclosed which check had failed, returning "Envelope replay detected"
for a replay but "envelope could not be parsed" for a malformed body. An
attacker probing the endpoint could tell exactly which control they had
tripped.

Fixed in `shared/errors.py`: every rejection now returns an identical body, with
the specific reason kept in the server log. The regression guard is
`test_every_envelope_rejection_looks_identical_on_the_wire`.

That is what the harness is for. It is worth writing up: a finding you found,
diagnosed and fixed yourself is stronger evidence of understanding than a
finding you only described.

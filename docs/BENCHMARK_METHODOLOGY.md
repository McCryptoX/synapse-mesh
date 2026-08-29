# Comparative Agent Evaluation Methodology

## Status

This document specifies a future comparative experiment. The repository does **not** currently contain a complete reproducible A/B/C run, so it publishes no comparative first-try rate, token saving, speedup, or hallucination reduction as product evidence.

The checked-in `Suite v2-runtime-9` corpus is a fixture-integrity gate for the verification machinery. Its numeric result is currently withheld because the frozen TypeScript N2 fixture does not reach its declared compiler fingerprint. It is separate from the experiment described here.

## 1. Research question

Does access to Synapse-Mesh improve a software agent's ability to fix preregistered compatibility failures when compared with the same model under a matched tool and budget policy?

The experiment must be capable of finding benefit, no effect, or harm. Its purpose is measurement, not confirmation.

## 2. Required preregistration

Before the first agent sees a case, publish or timestamp an immutable protocol containing:

- the exact case manifest and digest;
- inclusion and exclusion criteria;
- primary and secondary outcomes;
- sample size and analysis plan;
- model provider, immutable model snapshot or version, parameters, and system prompt;
- allowed tools and network policy for each arm;
- attempt, token, tool-call, and wall-clock budgets;
- timeout, retry, failure, refusal, and infrastructure-error rules;
- the Synapse catalog snapshot and digest;
- the judge implementation and environment;
- a contamination and conflict-of-interest statement.

Changing any of these after observing outcomes creates a new experiment. Deviations must be disclosed rather than silently folded into the original result.

## 3. Case selection

The comparative holdout must be selected independently of the recipes used to develop Synapse-Mesh and must not be tuned after seeing treatment results. Cases should cover several ecosystems and failure types while remaining individually reproducible.

Each case needs:

- a licensed, minimal unpatched workspace;
- exact dependency and runtime pins;
- an authentic expected pre-fail signature and exception class;
- a hidden acceptance suite that checks behaviour, not just source text;
- at least two plausible incorrect mutations;
- an official primary source where available;
- a declared time at which the compatibility change became public.

The frozen fixture corpus may be used to validate the judge, but using the same public cases to claim general agent advantage creates leakage and must be labelled as an in-sample diagnostic rather than a blind holdout.

## 4. Treatment arms

One useful incremental design is:

| Arm | Access |
|---|---|
| A — model only | The frozen model snapshot and the case workspace; no external retrieval |
| B — current documentation | The same model and workspace, plus a defined web/official-documentation tool policy |
| C — documentation plus Synapse | Everything available to B, plus the frozen Synapse MCP endpoint or snapshot |

Every non-treatment setting must be identical: prompt, model snapshot, context limit, temperature and sampling settings, machine resources, time budget, retry policy, and judge feedback. Tool latency and failures must be retained in the raw result.

Arm A measures a different question from the incremental B-versus-C comparison. The primary claim should be selected in advance; do not choose the most flattering comparison after the run.

## 5. Run procedure

For every case and treatment:

1. start a fresh agent session with no previous-case context;
2. provide the identical problem statement and clean workspace;
3. enforce the preregistered tool and budget policy;
4. record every model message, tool request, tool result, patch, retry, and timing event;
5. submit the candidate patch to the hidden judge without revealing hidden assertions;
6. preserve the first submission separately from later attempts;
7. stop at success or the preregistered budget;
8. classify infrastructure errors separately and apply the preregistered rerun rule.

Order should be randomised or counterbalanced. Repeated stochastic runs need independent seeds and a preregistered aggregation rule. If a provider cannot guarantee an immutable model snapshot, record that limitation and the run timestamp.

## 6. Judge requirements

The hidden judge must run the candidate patch against the same declared workspace and real dependency or compiler. It must check:

- authentic pre-fail before applying the candidate;
- safe and complete patch application;
- functional post-patch assertions;
- regression checks and negative mutations where applicable;
- exact toolchain versions.

The judge environment must be isolated from production data and credentials. The repository's current API-container runner is not a hostile-code boundary and is not sufficient for evaluating arbitrary model-generated code on a public server. Use a dedicated disposable environment and publish its measured controls.

Judge failure, missing dependencies, timeout caused by infrastructure, and unavailable services are not semantic passes or failures. Report them separately.

## 7. Outcomes

### Primary outcome

Choose one before the run. A defensible option is **first-submission hidden-judge pass rate**:

```text
cases passing on the first submitted patch
------------------------------------------
all eligible cases assigned to that arm
```

### Secondary outcomes

| Metric | Definition |
|---|---|
| Total solve rate | Cases passing within the complete preregistered attempt and budget limit |
| Failed patch count | Candidate patches rejected by the hidden judge before final success or stop |
| Input and output tokens | Provider-reported usage, retained separately and combined only by a declared rule |
| Tool calls | Count by tool name and success/failure status |
| Wall-clock time | Time from case delivery to accepted patch or stop, including tool latency |
| Synapse use rate | Cases in arm C where the agent actually called Synapse |
| Qualified Synapse hit rate | Arm-C cases where Synapse returned an evidence-qualified match under the frozen snapshot |
| Safety-policy violations | Attempts to access forbidden resources, leak secrets, or bypass judge controls |

Avoid the ambiguous term “hallucination” unless a blinded coding rubric defines it. A judge-rejected patch is directly measurable and should be reported as such.

## 8. Analysis

Publish numerator and denominator with every rate. Include uncertainty intervals and use paired methods when the same cases appear in multiple arms. Report per-case outcomes and ecosystem strata; an aggregate alone can hide failure modes.

Do not claim statistical significance unless the test, sidedness, alpha level, multiple-comparison handling, and sample-size rationale were preregistered. Do not claim causality beyond the randomised treatment difference actually measured.

Timing and token results depend on providers, networks, pricing, cache behaviour, and model versions. State the measurement window and avoid converting a single run into a permanent speed or cost claim.

## 9. Reproducibility artifact

A publishable result requires a machine-readable artifact containing:

- protocol and case-manifest digests;
- source revision and container or environment digests;
- model and tool identifiers;
- randomisation and seeds where available;
- raw prompts, outputs, tool transcripts, patches, and judge results;
- per-event timestamps and token accounting;
- all exclusions, retries, deviations, and infrastructure errors;
- an evaluator script that regenerates the tables from raw records.

Remove personal data, credentials, and proprietary material before publication. Redaction must be documented and must not change the scored substance. Respect model-output, source-code, and dataset licence terms.

## 10. Permitted result language

A result may state only what the frozen experiment measured, for example: “Under protocol X, model snapshot Y, and holdout Z, arm C passed n/N first submissions compared with m/N in arm B.”

It must not be generalised to “no hallucinations,” “works for all breaking changes,” “production safe,” or “faster for every agent.” A null or adverse result must be published with the same detail as a favourable one.

Until all required artifacts exist, the correct published comparative conclusion is: **no reproducible comparative result is available.**

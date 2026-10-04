# Hypothesis: Evidence-Grounded AI for Quant Crucible

## Status
Proposed hypothesis. Comparative evaluation has not yet been completed.

## Research Question
Can an AI assistant grounded in our repository explain and challenge
our systematic-trading research more accurately and transparently
than a generic AI chat interface?

## Main Hypothesis
Combining repository evidence, deterministic Python calculations,
Gemini explanations, and an ElevenLabs voice interface will produce
more accurate, specific, auditable, and context-aware answers about
Quant Crucible than a generic AI chat interface.

Text and voice will use the same answer pipeline, preserving the
selected symbol, date, module, and conversation context.

This improvement should occur without changing the underlying
trading strategies, risk controls, or execution logic.

## Why We Expect This
A generic AI assistant may give plausible market explanations without
knowing what our system actually recorded.

Our proposed assistant will retrieve relevant hypotheses, backtest
results, transaction-cost assumptions, risk-gate decisions, and
paper-trading records before answering.

Python will calculate numerical results. Gemini will explain the
evidence. ElevenLabs will provide speech interaction.

When evidence is missing, the assistant will state the limitation
or ask a clarifying question.

## Expected Behavior
The assistant should:
- Explain recorded strategy decisions using identifiable evidence.
- Support numerical claims with reproducible calculations.
- Distinguish actual results from hypothetical scenarios.
- Separate verified facts from possible explanations.
- Identify weaknesses in research, including small samples,
  overfitting, and survivorship bias.
- Preserve historical replay boundaries without revealing future
  outcomes early.
- Give consistent factual answers across text and voice.

## Evaluation Plan
Before testing, freeze a repository snapshot and prepare a fixed set
of questions with reference answers supported by that snapshot.

Include questions about strategy decisions, costs, risk gates,
research weaknesses, historical replay, and missing evidence.

Compare:
1. A generic Gemini chat interface without repository retrieval
   or deterministic tools.
2. The proposed repository-grounded Quant Crucible assistant.

Use the same Gemini model version and question set. Record the
context and tools available to each system. Repeat trials to measure
variation, and score answers without showing reviewers which
system produced them.

Measure:
- Factual and numerical correctness.
- Whether cited evidence actually supports the answer.
- Unsupported claims.
- Appropriate handling of missing information.
- Context retention across follow-up questions.
- Factual consistency between text and voice.

Set scoring rules and success thresholds before running the evaluation.

## Null Hypothesis
The repository-grounded assistant provides no measurable improvement
over the generic interface on the predefined evaluation.

## Limits
Better explanations do not establish trading profitability or prove
that the underlying research is valid.

Repository evidence may itself be incomplete or biased. The assistant
must expose these limitations rather than turn them into confident claims.

Simulated paper-trading results must remain clearly identified.

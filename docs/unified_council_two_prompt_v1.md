# Unified Council: two-prompt quarterly replay

The replay presents one AI Investment Council to the user, but executes two
sequential and independently validated prompts at every quarterly node.

## Decision sequence

1. **Factor Agenda** reads factor diagnostics, mechanisms, market evidence and
   accepted web sources. It selects only candidate factor groups allowed by the
   packet.
2. **Portfolio Agenda** receives the validated Factor Agenda result as an
   upstream artifact. It may select only `defensive`, `balanced` or
   `opportunistic`, plus an industry active tilt of `0`, `5%`, `8%` or `10%`.
3. The two outputs share one `round_id`. A node can be accepted only when both
   schemas validate and the Portfolio Agenda points to the same factor round.
4. A human instruction reruns both prompts in order. Changing factors therefore
   always invalidates and recomputes the downstream portfolio decision.

## Backtest connection

Acceptance writes two immutable audit files:

- `schedule_<node>.json` with quarterly factor groups;
- `portfolio_schedule_<node>.json` with the approved profile, beta policy and
  industry over/underweights.

The real pipeline maps both schedules to every five-session signal date. The
optimizer still owns individual security weights, futures hedge sizing, name
caps, gross exposure, turnover, cash and margin constraints. AI cannot create
an arbitrary exposure or trade.

## Research and showcase modes

Research mode forbids post-cutoff evidence. Because the current industry labels
come from a static 2026 snapshot, a research-mode Portfolio Agenda must remain
industry neutral when that snapshot is future-dated relative to the node.

Showcase reenactment remains explicitly labelled with the fixed hindsight
disclosure. Its demo director may select a bounded profile and industry targets
from the later segment outcome; the Council prompt must reproduce those targets
without presenting the retrospective selector as a live forecast.

## Stored audit fields

Each agenda stores its prompt hash, model, token usage, evidence IDs,
validation errors, confidence and rationale. Portfolio rounds additionally
store the selected profile, stock target, target beta, beta tolerance, industry
tilt, packet digest and the linked factor round.

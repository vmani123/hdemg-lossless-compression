# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**What's already been tried lives elsewhere** — read those first so you don't
re-propose a spent lever:
- `research/INSIGHTS.md` — the durable principles (P1–P5), the current open
  frontier, and the dead-ends list.
- `research/CYCLE_LOG.md` — the append-only per-cycle ledger (one row per cycle).
- `research/LEADERBOARD.md` — the current best + Pareto front.

## Verdict key
- **embeddable** — integer, causal, bounded state/look-ahead, fits the sEMG budget
  (≤1831 cyc/sample-ch) and plausibly the 30 kHz neural budget (125 cyc).
- **borderline** — embeddable only after a specific simplification (noted).
- **watch-list** — expected to fail the cost gate today; track, never auto-promote.

## Live embeddable candidates (not yet spent)

These are the forward proposals still open. The full mechanism rationale is in
`INSIGHTS.md`'s "Open frontier"; this table is the survey-side pointer with the
literature grounding.

**Update 2026-08-17:** candidates #1 and #2 below were tried (five parallel
cycles, 2026-08-05→2026-08-16, consolidated into one PR — see `CYCLE_LOG.md`
rows 16–30). #2 (temporal functional-form change) **succeeded** — a JPEG-LS/CALIC
per-context bias corrector is now the leaderboard best (INSIGHTS P9) — so #5
below is **partially spent**: the bias-correction half of the JPEG-LS mechanism
is done, the full MED/LOCO 2D-predictor replacement remains open. #1
(scale-selected spatial front-end) was attempted 3 independent ways and found
ratio-neutral-at-best every time (INSIGHTS P7) — kept on the list but re-ranked
down; do not attempt a 4th *learned/estimated* gate criterion without reading P7
first, a *decoder-observable* gate (channel count, à la `acar_sel`) remains the
one form proven to work.

| # | method | why it may beat the current best | verdict | key caveat |
|---|---|---|---|---|
| 1 | **Scale-selected spatial front-end** — gate `LMS4+Rice+xchan_mst`'s Chow-Liu tree (tight arrays) vs plain best-partner (large arrays) on the decoder-observable channel count | Tried 3 ways this round (MDL in-sample selection, backward rank-statistic, per-channel MDL+hysteresis) — all landed at or below the best of their own branches (P7); a *decoder-observable* channel-count gate (the only form proven to work, via `acar_sel`) is untried for this specific pairing | **embeddable** (both branches already verified; gate mechanism proven elsewhere) | P7's winner's-curse finding predicts a small or null result — budget accordingly, don't assume the branches' peak |
| 2 | **Non-linear temporal predictor** (functional form, order ≤4) — a small sign-of-neighbour or gated-magnitude nonlinearity | ~~A linear-LMS residual is white *to second order*~~ **partially addressed**: a context-conditioned *additive mean* correction (JPEG-LS-style bias cancellation) is now proven positive (P9, new leaderboard best) — but that's a first-moment correction, not a change to the predictor's functional form itself. A genuine non-linearity in the predictor is still untried | **borderline → embeddable** | still the only completely untouched temporal axis; lower priority than #1 now that #1 has a clearer next step (P9's context-sweep) |
| 3 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 4 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2) |
| 5 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **partially spent — borderline** | the *bias-cancellation* half of JPEG-LS is now proven positive and shipped (P9, `LMS4bc+Rice+xchan_bestpartner`); the *MED/LOCO predictor itself* (replacing the linear LMS, not just correcting its residual mean) remains untried. Entropy-context on the Rice parameter is still spent (P5) |

## Watch-list — DO NOT promote without human approval

Methods that fail the integer / causal / streaming gates today; tracked for
offline baselines and future reference only.

| method | note |
|---|---|
| Integer discrete flows (IDF), L3C, learned entropy models | learned lossless; float/GPU, no streaming budget — offline baselines only |
| Convolutional autoencoder + lossless residual | float core; disqualified on the FPGA target |
| VAE-DCT / neural context models | fail integer + latency gates today |
| TSCom-Bench / chained lightweight neural predictors (arXiv 2509.21002) | learned-lossless time-series; float/GPU, no streaming budget |
| GPU adaptive lossless FP framework (arXiv 2511.04140) | offline/GPU float pipeline; no integer streaming budget |
| Predictability-aware multichannel TS (arXiv 2506.00614) | lossy + neural + non-causal; disqualified, tracked for record |
| Compressive on-chip AP recording (IEEE TBME 11183845) | **LOSSY** (requantise + MI selective sampling); disqualified by lossless-only, listed for record |

**Reference-only (not a contender):** streaming floating-point time-series
compressors (Elf / Chimp / Gorilla, arXiv 2510.07015) are XOR-of-float oriented —
a poor fit for int16 biosignals where Rice/Golomb already dominates. A baseline
bar, not a candidate.

## The two settled spatial facts (from INSIGHTS, so the survey doesn't re-propose them)
- Cross-channel decorrelation is the dominant lever, but it's a **single rank-1
  adaptive subtract** — multi-tap transforms (fixed or adaptive) and summed
  multi-parent subtracts are dead ends (P3, P1b).
- The entropy back-end is at the floor — Rice is optimal for the near-geometric
  residual; neither an ANS swap nor any context-model of the Rice parameter helps (P5).

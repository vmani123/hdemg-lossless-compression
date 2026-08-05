# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**Last refreshed: survey pass 2026-08-05 (after cycle 15, `CYCLE_LOG.md`).** State
at refresh: 20 registered codecs, 9 retired; best embeddable
`LMS4+Rice+xchan_bestpartner` (cost 0.039), unbeaten across all 4 real sets since
cycle 7. Cycles 10–15 spent the *re-slicing* of the existing zero-lag spatial MI —
CAR cascade, scale-gated CAR (`acar_sel`), joint 2-parent (`joint2`), selected
best-pair (`jointbp2`), regime-switched predictor bank (`LMS4rs`, retired). Every
one of them landed within ~1% of a shared ceiling. **This refresh therefore turns
the slate away from re-dividing the same MI and toward levers that change the
bound itself** (candidate 1), fix a diagnosed *estimator* defect in the existing
selector (candidate 2), or fix a stagewise-objective mismatch in the cascade
topology (candidate 3). Superseded proposals from the previous refresh are moved
to "settled / superseded" below rather than deleted.

> **Cycle-log note — measured outcome of this refresh's candidates 1–3 (cycle 16,
> 2026-08-05, `results/cycle_bench.csv`).** All three were built, benched and unanimously
> verified; **none beat the best on real data**, and candidate 3 was retired.
> - #1 `xchan_lagpartner`: hyser 1.4762 (−0.28%), otb 2.0559 (−4.91%), **capgmyo 1.3575
>   (+0.52%, a new max)**, cemhsey 1.9534 (−0.11%). The τ\*=3–7-sample propagation slice
>   **does not exist**: τ=0 is chosen in 97.3% (hyser) / 97.6% (cemhsey) of blocks and
>   \|τ\|≥3 in ≤8.3% anywhere. Kept as the non-dominated max-CapgMyo corner (INSIGHTS **P1c**).
> - #2 `xchan_mdlsel`: within **±0.025%** of `jointbp2` on every real set, despite flipping
>   7.3–25.8% of the selected spatial orders. The selection surface is **flat** — median
>   3 bits per 256-sample block on flipped blocks (INSIGHTS **P1d**). Kept, not promoted.
> - #3 `xchan_post`: loses on all 4 real sets at *identical* cost → **RETIRED**; the reorder
>   alone still loses at matched block length, and its longer-block "mitigation" backfired in
>   both domains (INSIGHTS **P6** — spatial always goes first).
>
> **Next hypotheses, ranked by expected payoff (see `INSIGHTS.md` "Open frontier"):**
> 1. **Compose the two measured per-set maxima under the proven zero-side-info channel-count
>    gate** — `C≤64` → the `acar_sel` CAR-then-best-partner cascade (otb 2.1795, measured
>    tight-array max); `C≥128` → `jointbp2`'s joint best-pair (hyser 1.4969, measured
>    large-array max). Projected from measured cells: hyser +1.12%, otb +0.81%, capgmyo
>    −0.01%, cemhsey −0.17% vs best — the first construction to clear the best on the primary
>    *and* the tight array at once. Both branches and the gate are already verified ⇒ highest
>    payoff, lowest risk, cost ≈0.051. This **supersedes the "settled/superseded" note below**:
>    the objection there was that a geometry gate cannot pick the spatial *order* for CapgMyo,
>    but the measured cost of the large-array branch on CapgMyo is −0.01%, i.e. nil.
> 2. **Narrow-lag partner, τ ∈ {−1,0,+1}, gated on low ρ(0)** — the only positive real-data
>    finding of the lag axis, at ~1/8 the selection cost (13 options vs 29, cost ~0.045 vs
>    0.0775). ±1 is 72–83% of all non-zero lag selections; narrowing removes the winner's-curse
>    loss that sank OTB while keeping CapgMyo's +0.34%. Medium payoff (negative control cannot
>    move the headline), low risk.
> 3. **Non-linear temporal predictor, order ≤4** (candidate 4 below) — now the only untouched
>    axis. **New bar from P1d:** it must move the residual ≳0.1 bit/sample (~25 bits per
>    256-sample block) or the Rice back-end cannot express it. Highest mechanism risk.

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

| # | method | why it may beat the current best | verdict | key caveat |
|---|---|---|---|---|
| 1 | **Lag-matched (spatiotemporal) cross-channel partner** — `xchan_lagpartner`. Keep the proven **rank-1** adaptive subtract, but select the parent as a *(neighbour, integer time-lag τ)* pair, backward-adaptively per block; predict `x[c,t]` from `x[p, t−τ]` | **Attacks P1's bound instead of re-dividing under it.** P1 caps the spatial gain at the neighbour MI — but every codec so far measures that MI at **τ = 0 only**. HD-sEMG is dominated by MUAPs *propagating* along the fibre at 3–5 m/s, so the inter-electrode cross-correlation peaks at **τ\* = IED/CV ≠ 0**: 8–10 mm at 3–5 m/s = 1.6–3.3 ms = **3–7 samples at 2048 Hz** (Hyser/OTB/CEMHSEY). At the dominant 80–120 Hz sEMG band that is a ~90° phase error, so the *propagating* component of the shared source is nearly invisible to a zero-lag subtract. Residual variance goes `1−ρ(0)²` → `1−ρ(τ\*)²`; the bit saving is `½·log₂((1−ρ(0)²)/(1−ρ(τ\*)²))` per sample. This is a **new MI slice**, not a re-slice of the ~1%-spread family (cycles 10–15). Grounded in the standard HD-sEMG delay/conduction-velocity estimation literature (Farina & Merletti, inter-electrode delay estimation) — the same delay those methods *measure* is what the codec would *exploit* | **embeddable** | extra state = an L-deep int16 ring buffer of the reconstructed parent (L≤8 → ~16 B/ch, negligible). Selection cost grows ×L (4 parents × 8 lags); amortized over a 512-sample block it is fine at 2 kS/s but must be coarse→fine or subsampled to fit the 125 cyc/sample-ch neural budget. **Signed** τ (parent's future) is decodable at zero side-info under the existing channel-sequential order but costs ≤L samples (~2–4 ms) of bounded look-ahead; a τ≥0-only variant is strictly look-ahead-0. Predicted ≈null on CapgMyo (differential array already cancels the shared mode) — that is the negative control, not a failure |
| 2 | **MDL-penalized / out-of-sample spatial model-order selection** — `xchan_mdlsel`. Same candidate set as `jointbp2` (none / single parent / joint pair) but scored with a **parameter-count penalty** (`+ (k/2)·log₂B` bits, k = spatial taps) or on a **held-out block** (fit β on block i−2, score bits on block i−1) | Diagnoses and fixes a real estimator defect, not a parameter tweak. `_jbp2_select_block` scores every option by *in-sample* Rice bits of an LS fit on the previous block. A 2-parameter joint pair can **never** score worse than a 1-parameter single on the block it was fit to, so the selector is **structurally biased toward the higher order** — textbook model-order selection without a complexity term. That is exactly the observed failure signature: `jointbp2` wins the diffuse large array (Hyser +1.12%) but loses tight OTB (−0.45%), where P1b says the local MI is rank-1 and the second tap buys only estimation variance. A **penalized** or **validated** criterion makes order fall out of the data per channel *and* per block, at zero side-info — a strictly better realization of frontier #1 than the geometry heuristic (channel-count gate), which cannot explain CapgMyo (128 ch but |corr| 0.29) | **embeddable** (same ops as `jointbp2`, cost ≈0.047; penalty is one integer add per scored option) | not a re-proposal of a retired codec — `jointbp2` (cycle 13) is **active/non-dominated**; the change is the *selection criterion*, not the transform. Upside is bounded by the ~1% spread of the spatial family: best case ≈ jointbp2's Hyser **and** best-partner's OTB simultaneously, i.e. the first robust 4-set win since cycle 7. Must not silently become `xctx`-style modelling of the Rice *parameter* (P5) — the penalty gates the **transform order**, the coder is untouched |
| 3 | **Innovation-domain spatial subtract (stage reorder)** — `LMS4→xchan_post`. Run the order-4 temporal LMS **first**, per channel, then apply the proven rank-1 adaptive cross-channel subtract to the *innovation* sequences | Every registered codec is spatial-then-temporal (`_*_forward` → `ec.lms_forward`) — the reverse ordering is untried. Two theory reasons it should code fewer bits: (i) **stagewise objective mismatch** — the spatial stage currently minimizes *raw* residual power, but the quantity actually coded is the residual *after* whitening; the optimal spatial weight is the ratio of innovation cross-spectra, which is not the broadband raw LS β. Applying the subtract in the innovation domain makes the greedy stage minimize the objective the coder actually pays for. (ii) **The mixture is harder to whiten** — `x[c] − β·x[p]` mixes two AR processes, and a sum of AR(p) processes is ARMA of *higher* order than either, so a fixed order-4 whitener (mandatory per P2) systematically under-fits the very signal the current cascade hands it. Temporal-first never creates that mixture | **embeddable — cost-neutral** (identical ops and state, reordered; ≈0.039) | cheapest possible test of a real topology question. Risk: innovations are near-white and small-amplitude, so the sign-sign spatial tap sees a lower-SNR gradient and may adapt noisily — mitigate with a longer spatial time-constant. Distinct from P3's dead end: still a **rank-1 asymmetric subtract**, not a multi-tap/energy-preserving inter-channel transform |
| 4 | **Non-linear temporal predictor** (functional form, order ≤4) — a small sign-of-neighbour or gated-magnitude nonlinearity | A linear-LMS residual is white *to second order*; the only remaining temporal compressibility is higher-order. Multiplying linear coefficient sets is spent (`LMS4rs`, retired) — the form must genuinely change | **borderline → embeddable** | higher mechanism risk; still open, but ranked below 1–3 this refresh. NOT the retired regime bank / entropy-context levers (P2/P5) |
| 5 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 6 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2) |
| 7 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **borderline** | context state per gradient bucket × channel; must beat #1–#2 on a real 5×13/8×16 grid, not natural images. NB entropy-context on the Rice parameter is spent (P5) — the lever here is the 2D *predictor*, not the coder |

### Settled / superseded since the last refresh
- **Scale-selected spatial front-end gated on channel count** (previous #1): both
  per-scale branches and the zero-side-info gate are verified (`acar_sel`, cycle 15;
  `jointbp2`, cycle 13), but a *geometry* gate cannot separate CapgMyo (128 ch,
  neighbour |corr| 0.29 → wants no second parent) from Hyser (128 ch, |corr| high →
  wants one). **Superseded by candidate 2**, which gates on the data itself at the
  same zero side-info cost. Do not re-propose the bare channel-count gate.

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

## The settled spatial facts (from INSIGHTS, so the survey doesn't re-propose them)
- Cross-channel decorrelation is the dominant lever, but it's a **single rank-1
  adaptive subtract** — multi-tap transforms (fixed or adaptive) and summed
  multi-parent subtracts are dead ends (P3, P1b).
- The entropy back-end is at the floor — Rice is optimal for the near-geometric
  residual; neither an ANS swap nor any context-model of the Rice parameter helps (P5).
- The temporal predictor saturates at order ≈4, and **multiplying coefficient sets**
  (activity-regime bank, `LMS4rs`) fits noise and fragments adaptation — retired (P2).
- Re-dividing the **zero-lag** spatial MI (CAR, scale-gated CAR, joint pair, selected
  pair) has converged: every variant lands within ~1% of a shared ceiling. A candidate
  that only re-partitions that same MI should be expected to land there too — which is
  why candidate 1 changes *which* MI is measured and candidate 3 changes *where* in the
  cascade it is removed.

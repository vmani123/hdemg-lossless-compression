# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**Cycle note — survey refreshed 2026-08-07** (after cycle 15, `LMS4+Rice+acar_sel+bestpartner`;
best embeddable still `LMS4+Rice+xchan_bestpartner`, cost 0.039). Retired ledger re-checked
via `research/registry.py --selftest`: 9 of 20 registered codecs are RETIRED
(`xchan_adaptive`, `xchan_bestpartner`(o8), `iklt`, `iklt_adaptive`, `xchan_tans`,
`LMS4rs+…`, `acar+bestpartner`, `xchan_multiparent`, `xctx`) — none is re-proposed below.
This cycle adds one **new** mechanism to the live table: a **propagation-lag-aligned**
cross-channel partner (row 1). Audit finding that motivates it: **every** spatial front-end in
the registry (`+xchan`, `xadapt`, `bestpartner`, `acar`, `joint2`, `jointbp2`, and the retired
`iklt*`/`multiparent`) subtracts the partner at **lag 0 only** — `x[g] - (β·x[p])>>s` at the
same time index (`research/registry.py:353`). The time-shift axis of the dominant lever (P1)
has never been searched. Rows 2–3 are INSIGHTS frontier #1 and #2, carried forward.

**Post-measurement addendum — cycle 2026-08-07 results (rows 1–3 above are now SPENT).**
All three were built, double-verified (unanimous PROMOTE, no splits) and measured on the four
real sets (`results/cycle_bench.csv`). **None was promoted; two were retired.** Headline stays
`LMS4+Rice+xchan_bestpartner` (cost 0.039).
- Row 1 `xchan_lagbp` — **RETIRED**, dominated on all 4 real sets by `bestpartner_adaptive`
  (otb 2.0923× vs 2.1531×, −2.8%) at ~1.8× cost. Its own pre-registered falsification criterion
  (CapgMyo) fired. The physiological premise was right but the *sampling* premise was not: at
  1–2 kS/s with 4–10 mm IED the delay is **sub-sample**, so `I(x_g[t]; x_p[t−d])` peaks at `d=0`
  and the 9× wider argmin only buys selection variance (INSIGHTS **P1d**).
- Row 2 `xchan_scalesel` — **kept, not promoted**. The backward rank-2-benefit gate *works*
  (picks the right branch on both scales without seeing `C`; +1.17% over its rank-1 branch on
  Hyser, +0.04% over its rank-2 branch on OTB, best CapgMyo ratio of any codec) but is
  **ratio-neutral**: 4-set mean +0.044% vs best (INSIGHTS **P1c**).
- Row 3 `LMS4v2` — **RETIRED**, dominated on all 4 real sets at 1.5× cost. Surface EMG is a
  *linear* volume-conductor process ⇒ vanishing bispectrum ⇒ the quadratic taps estimate
  moments that are ≈0 and pay their estimator variance in coded bits (INSIGHTS **P2b**).

**Next hypotheses for the coming cycle, ranked by expected payoff** (consistent with the
refreshed INSIGHTS "Open frontier"; propose-only, as always):
1. **Non-local causal parent pool** (extends row 1's pool idea *without* its lag axis, and
   attacks the P1c ceiling directly). Every measured front-end draws its parent from the ≤4
   immediately-adjacent causal grid neighbours, so the measured ceiling may be the
   *neighbourhood's*, not the array's. A single motor unit's territory spans 5–10 mm and fires
   on many **non-adjacent** electrodes, so `I(x_c; x_p)` for a distant same-territory channel can
   rival an adjacent one. Keep rank 1, keep the proven per-block backward argmin, and only widen
   the **candidate pool** to a small set of distant causal channels (same column ±2 rows, or a
   fixed decimated stride). **Hard constraint from P1d:** keep the option count ≤8 against a
   256-sample block (or lengthen the block), or the added options are paid for in selection
   variance exactly as `lagbp` was. Highest expected payoff; medium mechanism risk.
2. **Reduce selector variance instead of adding degrees of freedom** — the direction *every*
   negative result this cycle points to. Hold the front-end fixed at `bestpartner_adaptive` and
   vary only the re-selection cadence: longer block / partner-decision hysteresis / a
   stickiness margin, so a stable parent stops re-paying estimation noise each block. P1c's
   CEMHSEY sub-min result shows switching an adaptive branch has a real transient cost. Cheap,
   low risk, expected ≤0.5% — but it is the only knob that *lowers* estimator variance.
3. **Diagnose the LZMA gap before designing for it.** Offline LZMA still leads on Hyser
   (1.67× vs 1.497×) and CEMHSEY (2.06× vs 1.956×) yet **loses** on OTB and CapgMyo — a
   signature of long-range repeated literals across the whole recording, which no order-4
   predictor + memoryless Rice coder can see. Run it as a **measurement, not a codec**: how much
   of LZMA's Hyser margin survives on the *post-`LMS4+xchan` residual stream*? ≈none ⇒ the gap is
   packing overhead and the frontier is closed; a lot ⇒ a bounded-window match/repeat stage is
   the next genuine lever. Lowest cost, and the only test that can establish whether ~1.5× is the
   embeddable Hyser ceiling.

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
| **1** | **Propagation-lag-aligned best partner** (`xchan_lagbp`) — extend the proven rank-1 subtract with a **time shift**: per channel, select `(partner p, integer lag d ∈ [0..D≈8], gain β)` and code `x_g[t] − (β·x_p[t−d])≫s`; `D` bounded, selection backward-adaptive per block (à la `bestpartner_adaptive`) | **New axis on the dominant lever (P1).** MUAPs *propagate* along the fibres at 3–5 m/s, so an electrode pair at 8–10 mm IED sees the **same** source delayed by ~1.6–3.3 ms = **~2–7 samples** at 1–2 kS/s. A lag-0 subtract can only cancel the zero-lag-aligned fraction; the cross-correlogram peak — the statistic MFCV estimation is built on — sits at `d = IED/CV ≠ 0`. Formally `I(x_g[t]; x_p[t−d*]) ≥ I(x_g[t]; x_p[t])`, so aligning the tap raises the *removable* cross-channel MI at unchanged rank-1 structure. The temporal LMS cannot fix this: it sees only the channel's **own** past. Two free bonuses: (i) at `d ≥ 1` the parent's whole previous time-sample is already reconstructed, so the causal `parent<g` constraint **disappears** → the full 8-neighbourhood (incl. down/right) becomes legal, roughly doubling the partner pool; (ii) it predicts a disproportionate gain exactly where lag-0 correlation is weakest | **embeddable** — integer-only, look-ahead 0, one rank-1 subtract per sample-ch (same as the best); extra state `D×C` int16 ring ≈ 2 KB at D=8/C=128 (trivial vs. STM32H745 SRAM, small BRAM); encoder selection cost ×(D+1) but amortised over a 512-sample block. Zero side-info in the backward-adaptive form | Innervation-zone channels have an ambiguous/near-zero delay peak — the search must keep `d=0` and *no-subtract* as candidates. Anisotropy: gain should concentrate along the fibre axis, not isotropically. Do **not** grow this into a multi-tap *spatial* transform (P3 dead end) — the tap count stays 1 in space |
| 2 | **Scale/rank-gated spatial front-end** (`xchan_scalesel`) — gate single selected best-partner vs jointly-solved best-pair on a **decoder-observable** variable (channel count, or better: a backward-computed rank-2 benefit statistic from the previous reconstructed block) | INSIGHTS frontier #1. The two per-scale winners are measured (best-partner wins tight arrays, joint best-pair wins large); a zero-side-info gate (proven by `acar_sel`) is the first construction that could win the primary Hyser *and* hold the tight OTB corner. Theory (P1b): local spatial MI is rank-1 on tight arrays, rank≥2 on diffuse large ones — so gate on the **rank**, and channel count is only a proxy for it | **embeddable** (both branches + the gate mechanism already verified) | ceiling is bounded by already-measured corners: a naive `C≥128` gate takes the joint-pair branch on CEMHSEY too, where it is ~−0.17% vs the best → a raw channel-count gate may not clear the best on *all* four sets. The backward rank statistic is the version worth building |
| 3 | **Volterra-lite degree-2 temporal predictor** (`LMS4v2`) — keep **one** order-4 sign-sign LMS coefficient set but augment its regressor basis with ~2–3 integer second-order product terms (e.g. `(x[t−1]·x[t−2])≫s`), leaky, same adaptation loop | INSIGHTS frontier #2, and the only live temporal lever. A linear predictor whitens only to **second order**; any residual compressibility is higher-order, and a degree-2 Volterra kernel is the leading term of *any* analytic nonlinearity. HD-sEMG is a non-Gaussian superposition of MUAPs through a nonlinear volume conductor, so a quadratic term is the principled first correction | **borderline → embeddable** (a few extra MACs + 2–3 weights/ch; must watch int overflow and use a large shift) | genuinely different from the **retired** `LMS4rs`: that duplicated *linear* coefficient **sets** under an activity gate (fragmenting adaptation, P2); this has **one** set in an **augmented basis** — no gating, no fragmentation. Still the highest mechanism risk of the three: quadratic regressors have high variance and can *amplify* noise. Pursue only if rows 1–2 don't clear the best |
| 4 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 5 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2) |
| 6 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **borderline** | context state per gradient bucket × channel; must beat row 1/2 on a real 5×13/8×16 grid, not natural images. NB entropy-context on the Rice parameter is spent (P5) — the lever here is the 2D *predictor*, not the coder |

### Row 1 — grounding and prior art

- **Standardised precedent.** MPEG-4 ALS's *Multi-Channel Correlation* (MCC) tool is exactly
  this construction: pick a **reference channel**, transmit a **lag**, and apply a short
  (3-tap) filter around it. Liebchen, *MPEG-4 ALS — The Standard for Lossless Audio Coding*
  (compression figures there are **paper-reported, unverified here**, and are for audio, not
  HD-sEMG). Dolby TrueHD/MLP inter-channel prediction likewise runs the other channel through
  a **delay buffer** (US 6,043,763 family). `compression_spec/candidates.md` already lists
  "richer cross-channel topologies … à la MPEG-4 ALS multichannel and Dolby TrueHD/MLP" as
  open — the **lag** half of that has never been implemented here.
- **Physiological basis.** Delay-of-cross-correlation-peak is the standard estimator of muscle-
  fibre conduction velocity from electrode arrays (`CV = d/τ`; Farina & Merletti and the
  array-optimal-conditions literature). It is a *measured, real* property of these grids, not
  an assumption.
- **An unexplained gap in our own corpus that this predicts.** `compression_spec/datasets.md`
  notes Hyser neighbour |corr| ≈ 0.90 / R² ≈ 0.92 while achieved `+xchan` gain is only ~+11%.
  That gap is currently attributed to spiky data (variance-R² overstating the lossless
  ceiling) — temporal misalignment of a propagating source is a second, *testable* contributor.
- **Falsifiable prediction (state before measuring).** The gain should be **largest on
  CapgMyo** — a differential/bipolar 8×16 array is a spatial derivative along the fibre axis,
  which suppresses the lag-0 common part (measured neighbour |corr| ≈ 0.29, the negative
  control where every spatial lever so far gained ≈ +1.3%) while *preserving* the delayed-
  replica structure. If `xchan_lagbp` does **not** move CapgMyo, the mechanism is wrong and
  the row should be retired rather than tuned.
- **Sub-variant, not a separate candidate:** the true delay `IED/CV` is **fractional** in
  samples, so a 2-tap linear-interpolating fractional delay on taps `{d, d+1}` (i.e. ALS-MCC's
  filter-around-lag) is the natural refinement. Try the single-integer-lag form first — P1b's
  lesson is that extra degrees of freedom only pay where the MI is genuinely there.

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

**Scope clarifier for P3 (added 2026-08-07):** "rank-1 beats multi-tap" is a statement about
the **spatial** support — one partner channel, not a rotation/matrix over the neighbourhood.
It says nothing about **which time index** of that one partner is subtracted. Row 1 keeps the
spatial rank at 1 and moves only along the time axis, so it is *not* a re-proposal of the
retired `iklt` / `iklt_adaptive` / `xchan_multiparent` family. Any future variant that grows
the number of *spatial* taps is still a dead end.

# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

> **Survey cycle note — 2026-08-16 (RESULTS, after measuring the slate below).** All three
> candidates measured on the 4 real sets (`results/cycle_bench.csv`); **none promoted**, the
> headline `LMS4+Rice+xchan_bestpartner` stands. `xres` **RETIRED** (worse on all 4 at
> *identical* cost — the per-channel LMS high-pass destroys the shared low-frequency mode
> that carries the inter-channel MI, so `ρ_e ≪ ρ_x`; stage order beats estimator matching,
> INSIGHTS **P7**). `xlag` spent **negative** (a strict-superset ≤72-option search *lost*
> 6.1 pp of OTB xchan gain — selection variance over a large hypothesis set on 248
> samples/block, and the neighbour cross-spectrum is dominated by its zero-phase term
> anyway; also the only codec failing `neural_ok`; verifiers **REJECT/REJECT**, INSIGHTS
> **P6**). `xtree` is the cycle's real positive: the **highest OTB cross-channel gain of any
> codec (+18.32%)**, but its Chow–Liu structural advantage decays monotonically with array
> size (+0.96 pp at C=64 → +0.39 pp at C=128 → −0.06 pp at C=320) because ≈5C edge weights
> are estimated from one 256-sample block — the incumbent's 4-neighbour raster set is an
> accidental **regularizer** (INSIGHTS **P8**). The pairwise spatial edge is now fully
> explored in **lag, domain and graph**; what is left is not new mechanism but **better
> funding of the backward estimator** and **scale gating**.
>
> **Next hypotheses, ranked by expected payoff** (mirrors the refreshed `INSIGHTS.md`
> frontier; proposals only, nothing measured):
> 1. **Scale-gated `xtree`** — spanning tree for `C≤64`, raster `bestpartner` for `C≥128`,
>    on the decoder-observable channel count (the zero-side-info gate `acar_sel` already
>    proved). Both branches are bit-exact-verified and the numbers already exist: OTB
>    ≈2.1707× with the incumbent's Hyser/CapgMyo/CEMHSEY *exactly* preserved — the first
>    construction with **no real-set regression at all** — and it sheds the tree's cost
>    (0.0733→0.0394) on the arrays where it never pays. *Caveat:* `acar_sel` already owns
>    the OTB corner at 2.1795×/0.043, so measure the two gates **composed** before claiming
>    a win; likely a kept non-dominated corner, not a headline promotion.
> 2. **Fund the backward estimator instead of widening the model** (the binding constraint
>    identified by P6+P8). Zero added model freedom: (a) exponentially-weighted edge
>    statistics pooled across blocks (leaky accumulators — `xtree` already allocates the
>    state) so each selection sees an effective ~1–2 k-sample window; (b) hysteresis /
>    switch-cost so a partner only changes when the estimated saving beats the incumbent by
>    a margin. Best-partner identity is slowly varying (P4), so this should cost ≈0 ratio
>    and strictly cut variance. Retrofit onto `bestpartner_adaptive` first — a clean
>    single-variable test of the P6/P8 thesis, and it would also rescue `xtree` at C≥128.
> 3. **Non-linear temporal predictor (functional form, order ≤4)** — item #5 below,
>    unchanged in substance but now the **only untouched axis left**: the linear-LMS
>    residual is white to second order, so any remaining temporal compressibility is
>    higher-order. Highest risk, weakest pre-measurement entropy argument; pursue if #1/#2
>    do not clear the best.
>
> **Survey cycle note — 2026-08-16 (BEFORE measurement, after cycle 15).** Frontier #1 as written in
> `INSIGHTS.md` is now effectively closed by measurement: `jointbp2` (cycle 13) proved
> the selection+count stack works on large arrays but loses the tight-array corner, and
> `acar_sel` (cycle 15) proved the zero-side-info channel-count gate. Gating
> `bestpartner`(C≤64) vs `jointbp2`(C≥128) is arithmetic on already-measured numbers
> (wins Hyser, ties OTB, −0.01/−0.17% on CapgMyo/CEMHSEY) — kept below as a low-risk
> engineering option, **not** a headline candidate. This cycle's slate therefore opens
> **three previously unsearched axes of the pairwise spatial lever**, each rank-1 (so
> none re-enters P3's dead multi-tap end): the **temporal alignment of the edge**
> (`xlag`), the **domain in which the edge is fitted and scored** (`xres`), and the
> **graph topology + coding order** of the edges (`xtree`). Every registered/retired
> cross-channel codec to date shares three unexamined assumptions — the parent is taken
> at **lag 0**, the subtract happens **before** the temporal LMS and is scored on the
> **pre-LMS** residual, and parents are restricted to **4 raster-causal grid
> neighbours** — and the three candidates attack exactly one of those each.

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
| 1 | **`xlag` — lag-aligned cross-channel predictor.** Extend per-channel best-partner selection from *(parent)* to *(parent, integer delay d)*: subtract `β·x_p[t−d]` instead of `β·x_p[t]`, re-selected backward per block, scored in Rice bits → zero side-info | HD-sEMG is a **travelling-wave** field: MUAPs propagate along the fibre at 3–5 m/s, so at 8–10 mm IED / 2 kS/s the same MUAP reaches a neighbour ~2–3 ms ≈ **4–7 samples** later. The rank-1 coding gain is `½log₂(1/(1−ρ²))` at `ρ_max = max_d ρ_cp(d) ≥ ρ_cp(0)` — **every** xchan codec so far maximizes over *parent* but is pinned at **d=0**, so it can only cancel the zero-phase part of a cross-spectrum whose dominant term is a pure linear phase. Bonus: with `d≥1`, `x_p[t−d]` is already reconstructed for **every** p, so the causal `idx<c` restriction lifts and all 8 grid neighbours become legal parents | **embeddable** — +1 mul/shift per sample (unchanged), + a D-deep ring buffer/channel (D≤8 → ~2 KB at 128 ch); selection sweep `|cands|×D` amortized over the 512-sample block. Cost band ≈ `bestpartner_adaptive` | keep it **single-delay rank-1** (one gain, one lag) — a multi-lag cross-FIR (MPEG-4 ALS's 3-tap cross filter) drifts toward P2/P3's noise-fitting failure. Keep `d=0` and `no-parent` in the scored option set so the search is a **strict superset** of the incumbent's. Expect ≈0 on CapgMyo (differential array already differentiates along the fibre) — the standing negative control |
| 2 | **`xres` — residual-domain cross-channel prediction with a bit-matched selection criterion.** Reorder the pipeline: order-4 temporal LMS **first**, then the rank-1 adaptive subtract between *temporal residuals* (`e_c − β·e_p`), with the partner scored on the **post-LMS** residual bits | Two independent arguments. (i) Volume conduction is instantaneous linear mixing of shared MU innovation trains; the channels' shared **autocorrelation** (low-frequency, high-energy) is removed by the per-channel predictor *for free*, so a β fitted on raw signals spends its single degree of freedom on redundancy that dies downstream. Fitting β on the innovations targets the band where the coded bits actually live, and the innovation mixing coefficient is more stationary → a less biased backward estimate. (ii) **Criterion mismatch:** `_bp_score` today ranks partners by the Rice length of the *pre*-LMS residual while the encoder emits the *post*-LMS one — an argmin of a proxy, not of the objective. This makes scored quantity = coded quantity. Anchor: MPEG-4 ALS joint/multi-channel coding operates on *prediction residuals* and gates on residual cross-correlation (paper-reported, unverified here) | **embeddable** — identical op count and state to the incumbent, no new buffers; only the stage order and the scoring domain change. Cost ≈ 0.039. Still per-sample causal (decode channel-order within each time step, as now) | honest failure mode: if the innovations' `ρ_e` is materially below the raw `ρ_x`, the residual-domain subtract recovers less. That is precisely what the measurement decides — no ratio claim here |
| 3 | **`xtree` — Chow–Liu maximum-coding-gain spanning-tree pairing.** Replace the fixed 4-neighbour candidate set + raster order with a backward-derived **maximum-weight spanning tree** over channels (edge weight = estimated bits saved by a rank-1 subtract), coded in the tree's topological order. Each edge stays one rank-1 adaptive subtract | **Chow–Liu:** among all first-order (tree) dependency structures, the one minimizing KL divergence to the true joint is the max-weight spanning tree with MI edge weights; for jointly Gaussian channels edge MI is `−½log₂(1−ρ²)` = exactly the rank-1 pairwise coding gain. The incumbent's per-channel greedy over **raster-causal** neighbours is a provably sub-optimal constrained tree: it forbids half of each channel's spatial neighbourhood (right/down are `idx>c`) and picks greedily under a fixed order. The MST relaxes both at **zero side-info** — the decoder recomputes the same tree and order from the previous reconstructed block | **borderline → embeddable.** Prim on a dense C-node graph is O(C²) once per block (trivial), but dense edge weights cost ~64 extra MAC/sample-ch at C=128 — inside the 1875 cyc sEMG budget, **outside** the 125 cyc neural budget. Ship the **radius-restricted** edge set (8-neighbourhood + same-column ±2, ~10 edges/channel) to clear both | in a volume-conduction field the top-MI edges probably *are* the nearest neighbours, so the tree may reproduce a near-grid structure. Payoff concentrates in (a) the freed right/down directions and (b) raster-boundary channels (row 0 / col 0) that today have 0–1 candidates. Measure alone before composing with #1 |
| 4 | **Scale-gated `bestpartner`(C≤64) / `jointbp2`(C≥128)** — the literal frontier-#1 construction | both branches and the channel-count gate are already verified (`acar_sel`) | **embeddable — low-risk engineering option, not a headline** | outcome is predictable from cycles 13/15 numbers (wins Hyser, ties OTB, small CapgMyo/CEMHSEY regressions) → would not clear the "robust across real sets" promotion bar |
| 5 | **Non-linear temporal predictor** (functional form, order ≤4) — a small sign-of-neighbour or gated-magnitude nonlinearity | A linear-LMS residual is white *to second order*; the only remaining temporal compressibility is higher-order. Multiplying linear coefficient sets is spent (`LMS4rs`, retired) — the form must genuinely change | **borderline → embeddable** | still the weakest-grounded live lever; no specific form yet has a pre-measurement entropy argument. NOT the retired regime bank / entropy-context levers (P2/P5) |
| 6 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 7 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2) |
| 8 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **borderline** | context state per gradient bucket × channel; must beat #1 on a real 5×13/8×16 grid, not natural images. NB entropy-context on the Rice parameter is spent (P5) — the lever here is the 2D *predictor*, not the coder |

### Not re-proposed (checked against the retired ledger, 9 retired codecs)
The 9 retired entries in `research/registry.py` (`--selftest` prints each with a RETIRED
tag) are: `xchan_adaptive`, the order-8 `LMS+Rice+xchan_bestpartner`, `iklt`,
`iklt_adaptive`, `xchan_tans`, `LMS4rs+…`, `acar+bestpartner`, `xchan_multiparent`,
`xctx` — all conclusively Pareto-dominated; **none returns above**, and no candidate in
this slate is a parameter variant of one. Two near-misses worth naming explicitly:
- A per-block **MDL/rate-scored spatial model-order choice (none / single / pair)** is *already*
  implemented inside `_jbp2_select_block` — not a new candidate.
- The ALS-style **multi-tap cross-channel FIR** is deliberately *not* proposed; #1 takes only
  its single best delay, because the multi-tap form re-opens the failure mode that retired
  `iklt` (P3) and `LMS4rs` (P2) — fitting noise with extra taps.

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

## Literature grounding for this cycle's slate

All ratios below are **paper-reported, unverified here** — cited for the *mechanism*, never
as a bar.

- **Propagation / travelling-wave structure of HD-sEMG (grounds `xlag`).** Spatio-temporal
  HD-sEMG images render MUAPs as *linear structures whose angle to the time axis is set by
  the motor-unit conduction velocity* — i.e. the array's inter-electrode correlation peaks at
  a non-zero lag along the fibre direction
  ([MDPI Appl. Sci. 10(15):5099](https://www.mdpi.com/2076-3417/10/15/5099)). Delay
  estimation between EMG channels is a mature, well-posed problem (generalized
  cross-correlation / multichannel ML CV estimators, Farina–Merletti lineage). An HD-EMG
  compression study also reports that **the transversal (across-fibre) vs longitudinal
  channel ordering changes the achievable compression**, consistent with a
  direction-dependent, propagation-driven redundancy
  ([PMC3984708](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3984708/)).
- **Residual-domain inter-channel coding (grounds `xres`).** MPEG-4 ALS removes inter-channel
  redundancy by joint channel coding applied to the **prediction residual** signals, and its
  joint-coding decision is driven by the **cross-correlation of residuals**, which is used to
  estimate the compression improvement
  ([Liebchen et al., MPEG-4 ALS](http://elvera.nue.tu-berlin.de/files/1216Liebchen2009.pdf);
  [Sensors 14(9):17516, low-complexity joint coding for portable medical devices](https://pmc.ncbi.nlm.nih.gov/articles/PMC4208236/)).
  The same architecture has been applied to multi-channel ECG.
- **Tree-structured channel pairing (grounds `xtree`).** The Chow–Liu construction gives the
  optimal first-order (tree) approximation to a joint distribution as the maximum-weight
  spanning tree under pairwise-MI edge weights
  ([Chow–Liu tree models](https://www.emergentmind.com/topics/chow-liu-tree)); CL trees have
  been fitted directly to multichannel EEG spatial dependence
  ([PubMed 26070267](https://pubmed.ncbi.nlm.nih.gov/26070267/)). On the compression side,
  low-complexity multichannel ECG work explicitly **arranges mutually dependent channels into
  a tree so the maximum number of channels benefit from cross-prediction**
  ([Biomed. Signal Process. Control, selective linear prediction](https://www.sciencedirect.com/science/article/abs/pii/S1746809419302861));
  channel-clustering variants exist for EEG
  ([BSPC 2016](https://www.sciencedirect.com/science/article/abs/pii/S1746809416301252)).

## The two settled spatial facts (from INSIGHTS, so the survey doesn't re-propose them)
- Cross-channel decorrelation is the dominant lever, but it's a **single rank-1
  adaptive subtract** — multi-tap transforms (fixed or adaptive) and summed
  multi-parent subtracts are dead ends (P3, P1b).
- The entropy back-end is at the floor — Rice is optimal for the near-geometric
  residual; neither an ANS swap nor any context-model of the Rice parameter helps (P5).

**…and the three assumptions inside that settled fact that were never tested** (this
cycle's slate, one candidate each): the rank-1 edge is always taken at **lag 0**; it is
always fitted and scored **before** the temporal predictor; and its parent is always drawn
from **4 raster-causal grid neighbours**. Each is a free parameter of the winning mechanism,
not a proven optimum — and all three stay strictly rank-1, so none re-enters P3's dead end.

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

> **Survey cycle note — 2026-08-13.** Retired ledger re-checked against
> `research/registry.py --selftest` (20 codecs, **9 RETIRED**: `xchan_adaptive`,
> `xchan_bestpartner`(o8), `iklt`, `iklt_adaptive`, `xchan_tans`, `LMS4rs`,
> `acar+bestpartner`, `xchan_multiparent`, `xctx`). **None of this cycle's three
> proposals re-proposes a retired mechanism** (verified by grep: the registry
> contains no lag/delay, no spanning-tree/topology, and no conditional-mean
> bias-correction primitive — every existing cross-channel front-end subtracts a
> parent at **zero lag** from a **raster-causal** 4-neighbour set, see
> `_bp_candidates` / `_bp_select`).
> This cycle opens a **new axis inside the proven dominant lever (P1)**: the
> existing spatial front-ends vary *which* parent and *how many*; all of them are
> **instantaneous** and **geometry-ordered**. Candidates 1 and 2 attack the two
> structural constraints nobody has touched — the **zero-lag** assumption and the
> **raster-causal** parent set. Candidate 3 is the one live temporal axis
> (INSIGHTS frontier #2: change the predictor's *functional form*).
> Prior top-of-table item (scale-selected front-end) demoted to an
> engineering/closure item — see the note under the table for why its 4-set
> outcome is now largely determined by already-measured branch ratios.
>
> **Outcome of the 2026-08-13 cycle (measured, real data — analyst addendum).**
> Candidate 1 `xlag` **RETIRED** (worse on all 4 real sets than the lag-0 codec it
> reduces to, otb −2.82%, at 2.6× cost and failing `neural_ok`). Candidate 2 `xmst`
> **kept, not best** (isolated topology gain +0.36% hyser / +0.79% otb / ≈0 on the
> large arrays). Candidate 3 `biascorr` **PROMOTED — new best ratio**
> (hyser 1.4851×, otb 2.1934×, capgmyo 1.3531×, cemhsey 1.9553×; 4-set mean +0.555%),
> at cost 0.1202 — so it did **not** displace the port pick. Rows 1 and 2 of the table
> above are now spent: see `research/INSIGHTS.md` P1c (dead: parent lag; marginal:
> topology), P2b (predictor *functional form* CONFIRMED as a live lever) and P4b
> (backward-search width carries a winner's-curse variance price).
>
> **Next hypotheses, ranked by expected payoff** (mirrors the refreshed INSIGHTS
> frontier; proposals only, nothing measured):
> 1. **Shrink the corrector's context** (`biascorr-lite`) — the promoted win costs
>    0.082 of SRAM for 120 B/ch of 30-bucket accumulators. Ablate to ~6–8 buckets
>    (drop the `e[t−2]` axis and/or the parent-sign bit, which are the least
>    theoretically justified) and/or share `μ` tables across a grid row. Target ≥70%
>    of the +1.46% OTB gain at cost ≤0.06. **Highest payoff:** it is the only route by
>    which the new best also becomes the codec to port. Low mechanism risk — the
>    mechanism is already proven on real data.
> 2. **Normalized / leaky sign-LMS (order ≤4)** — remove the bias at its source rather
>    than correcting it after the fact. `biascorr` earns its gain from sign-sign LMS's
>    fixed-step misadjustment during amplitude transients; a step scaled by a backward
>    power estimate is unbiased under ramps by construction, at ~0 extra SRAM. Falsifiable
>    prediction: the gain should concentrate on the burstiest set (OTB), and stacking it
>    with `biascorr` should yield markedly *less* than the sum of the two. Medium payoff,
>    genuinely different axis. (Also revives watch-list row 5 with a specific rationale.)
> 3. **Scale-selected spatial front-end, now STACKED with the corrector** — the demoted
>    closure item, but the arithmetic changed: `LMS4bc` moved the tight-array corner to
>    2.1934× while `jointbp2` still holds max Hyser (1.4969×). A `C`-gated
>    (best-partner+bc at `C≤64` / jointbp2+bc at `C≥128`) composition is the only
>    construction that could hold both corners at once. Lowest mechanism novelty, but its
>    4-set profile is no longer predictable from the branch ratios alone.

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
| **1** | **Propagation-delay-aligned cross-channel prediction** (`xlag`) — subtract the best causal parent at a backward-selected **lag** `d ∈ {0…D}` (`x_c[t] − (β·x̂_p[t−d])>>s`), `(p,d,β)` re-picked per block from the previously reconstructed block | Every registered front-end subtracts a parent at **lag 0**, which only captures the *instantaneous* (transversal / common-mode) slice of the cross-channel MI. HD-sEMG is dominated by MUAPs **propagating along the fibres at ~3–5 m/s**: at 8–10 mm IED and 2048 Hz the along-fibre neighbour is a near-replica delayed by **≈2–5 samples**, i.e. ~¼ cycle at the 100 Hz spectral peak — a zero-lag subtract sees a *phase-rotated* copy and throws that MI away. Aligning the lag converts a decorrelated pair into a high-coherence one, so it enlarges the very lever P1 says dominates, rather than re-dividing it | **embeddable** — d≥0 uses *older* parent history ⇒ strictly more causal than today; +D int16/ch of ring buffer (D=8 → 2 KB @128 ch); zero side-info (decoder mirrors the search). Selection cost: 4→~4×(D+1) block-scored candidates; keep the 30 kHz neural budget by refining `d` only for the winning parent and re-searching every K blocks (CV is slowly varying) | not a variant of best-partner (*which* parent) or joint-pair (*how many*) — it changes the predictor's **support in time**. Risk: if the arrays are mounted transversally the winning `d` collapses to 0 and the gain vanishes (a clean falsifiable prediction). Upside test: **CapgMyo** — the differential array kills the zero-lag common mode (|corr| 0.29) but *cannot* kill propagation delay, so it is the set where lag alignment should show a gain the negative control has never given |
| **2** | **Max-MI spanning-tree channel topology** (`xmst`) — replace the raster-causal 4-neighbour parent set with a **Chow-Liu maximum-weight spanning tree** over the channel graph (edge weight = backward-estimated pairwise MI / coded-bit saving on the previous block), code channels in tree order, one rank-1 adaptive subtract per edge | `_bp_candidates` only offers parents with **index < c** on a raster scan: exactly **half the 8-neighbourhood (right, down, down-left, down-right) is structurally unreachable**, and greedy per-channel picks under an arbitrary order are not the optimal parent structure. Chow-Liu (1968) proves the maximum-weight MI spanning tree is the tree factorization **minimizing KL to the true joint** — i.e. the entropy-minimizing rank-1 dependency structure, exactly the object the front-end approximates. Edge channels and any channel whose strongest correlate lies "later" in raster order are currently coded against a strictly weaker parent | **embeddable** — candidate edges restricted to the 8-neighbourhood (or radius-2) ⇒ ~2× the current selection cost; Kruskal/union-find over ~500–1500 edges per block is <0.05 ops/sample-ch; state = parent[] + tree order (2C bytes). Integer-only (compare bit-scores by cross-multiplication, reusing `_bp_score`). Zero side-info: the tree is rebuilt by the decoder from reconstructed history | changes the **decode order** to a tree traversal (indirect BRAM addressing on the Spartan-7 — cheap, but note it in the port). Stays rank-1 per node, so it does **not** touch the multi-tap-transform dead end (P3) nor the summed-multi-parent dead end (P1b) |
| **3** | **Context bias-cancellation two-stage predictor** (`biascorr`) — after the order-4 sign-sign LMS, subtract a backward-adaptive **integer running-mean correction** `μ[ctx]` indexed by a tiny context (quantized signs/magnitudes of the last two residuals + the sign of the parent's residual), JPEG-LS/CALIC-style | The only live temporal lever (INSIGHTS frontier #2): a linear predictor is white only *to second order*, and sign-sign LMS is not even MMSE-optimal — its gradient-noise misadjustment leaves a **context-dependent non-zero conditional mean**. `H(e) ≥ H(e − E[e|ctx])`; removing the DC lowers residual variance by `E[μ_ctx²]`, worth ≈ `½log₂(1 + E[μ²]/σ²)` bits/sample. This is the mechanism that gives JPEG-LS its measurable gain over bare MED | **embeddable** — one accumulator + count per context bucket (≤32 buckets × C), correction by shift-divide; no multiplies, no look-ahead, zero side-info | **explicitly not** the retired levers: `xctx` conditioned the Rice **scale** `k` (already tracked by adaptive-k, P5) and `LMS4rs` forked whole **coefficient sets** by activity regime (fragmented adaptation, P2). This conditions neither — one global predictor, one additive **conditional-mean** term. Expected gain is small (~1–2% by image-coding analogy); run only alongside a spatial candidate |
| 4 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 5 | **NLMS / leaky sign-LMS + Rice** (MPEG-4 ALS RLS-LMS direction) | normalised/leaky adaptation may track non-stationary EMG better, still one-pass | **embeddable** | our search shows order>4 *hurts* real HD-sEMG — keep order small (P2) |
| 6 | **JPEG-LS / LOCO-I(-ANS) 2D over the grid×time image** | MED/LOCO predictor + context + Golomb exploits 2D spatial structure; LOCO-ANS is a proven low-complexity FPGA encoder | **borderline** | context state per gradient bucket × channel; must beat #1 on a real 5×13/8×16 grid, not natural images. NB entropy-context on the Rice parameter is spent (P5) — the lever here is the 2D *predictor*, not the coder. Partly subsumed by #3, which takes JPEG-LS's *bias-correction* idea without its image-tuned MED predictor |

**Demoted — engineering/closure item, not a mechanism slot: scale-selected spatial front-end**
(gate single selected best-partner at `C≤64` vs jointly-solved best-pair at `C≥128`; INSIGHTS
frontier #1). Both branches and the channel-count gate are separately verified, so a gated
composition's 4-set profile is now **largely determined by already-measured branch ratios**:
the `C≥128` branch (`jointbp2`, cycle 13) wins Hyser but is ≈neutral on CapgMyo and *below* the
best on CEMHSEY, so no gate over those two branches can produce the clean 4-set win the promotion
bar requires, and it lands at a higher cost than the incumbent. Worth building as a cheap closure
experiment (it would formally settle frontier #1 and give the max-Hyser + max-OTB corners in one
codec), but it is a **composition of verified primitives, not a new mechanism** — hence it does
not consume one of this cycle's distinct-mechanism slots.

### Literature grounding for the new entries
- **#1 lag** — the MPEG-4 ALS **multichannel coding tool** performs an adaptively weighted
  subtraction against a *selected reference channel* through a **time-lagged cross-prediction
  filter** (3-tap, sampling-rate-dependent lag range); applied to multichannel ECG/biomedical by
  Tanaka et al. Physiological basis: muscle-fibre conduction velocity is *itself* estimated by
  maximizing the cross-correlation between along-fibre adjacent HD-sEMG channels **at a delay**
  (Farina & Merletti; openhdemg tutorial), with XCC ≥0.7–0.8 at the correct lag. Itiki, Furuie &
  Merletti (BioMed Eng OnLine 2014, 13:25) further report that *transversal* channel ordering
  behaves differently from longitudinal for HD-EMG compression — consistent with the claim that
  the along-fibre MI is only reachable with a delay. (No ratios quoted; all
  paper-reported/unverified here.)
- **#2 tree** — Chow & Liu (IEEE Trans. IT, 1968): the maximum-weight MI spanning tree minimizes
  KL divergence among all tree-structured approximations. Prior art for correlation-driven (rather
  than geometry-driven) channel grouping in biosignals: "Efficient lossless multi-channel EEG
  compression based on **channel clustering**" (Biomed. Signal Process. Control, 2016) and
  "Low-complexity lossless multichannel **ECG** compression based on **selective linear
  prediction**" (2019) — the latter is the single-parent-selection analogue we already ship;
  the tree is its global-optimality upgrade. (Paper-reported, unverified here.)
- **#3 bias cancellation** — JPEG-LS / LOCO-I (Weinberger, Seroussi & Sapiro) and CALIC use a
  per-context running-mean **bias corrector** on top of the predictor; standard, integer-only,
  and the canonical demonstration that a linear/median predictor leaves a context-dependent
  conditional mean on the table. (Paper-reported, unverified here.)

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

**…and the two spatial facts that are NOT settled** (why this cycle's #1 and #2 are new,
not re-litigation): every spatial result so far — `xchan`, `bestpartner`, `joint2`,
`jointbp2`, `acar`/`acar_sel` — varies only **which** parent and **how many**. All of them
subtract the parent at **lag 0**, and all of them draw parents from the **raster-causal**
4-neighbour set. The rank-1-adaptive-subtract verdict (P3) constrains the *form* of the
subtract; it says nothing about its **time offset** (#1) or the **graph** the parents are
drawn from (#2). Both remain untested primitives, and both keep the subtract rank-1.

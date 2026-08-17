# INSIGHTS — distilled learnings for codec selection

**Read this first, every cycle.** This is the durable, theory-rooted knowledge
base: what the harness has **proven on REAL HD-sEMG** about which compression
mechanisms work here and *why*, stated so it guides the next candidate. It is the
condensed successor to ~15 cycles of `experiments/NNN_*.md` (kept as the detailed
record) and the append-only `CYCLE_LOG.md`.

**Maintenance:** after a cycle's measurement + verification, refine the relevant
principle with the new evidence — but only a learning **measured on real data**
(synthetic is mechanism-illustration only), and always state the *theory* for why
it holds, not just the number. A number without a mechanism doesn't generalize.

**Latitude:** candidates need not come from a paper. Designing a **novel** codec by
combining the primitives (predictive coding, reversible integer transforms/lifting,
context modeling, Golomb/Rice, ANS) is welcome **if rooted in sound theory** — you
can state *why* it should lower residual entropy or decorrelate the array better
before measuring. Every design still faces: lossless + bit-exact, `embedded_ok`
(see `EMBEDDED_OK_VERIFICATION.md` for what that gate really proves), real-data-decides.

---

## The current best

`LMS4bc+Rice+xchan_bestpartner` — the proven best-partner front-end (order-4
sign-sign LMS + best-of-4 causal-neighbour cross-channel subtract) plus a
**JPEG-LS/CALIC-style backward-adaptive per-context running-mean bias
corrector** (30 buckets, divisionless, zero side-info) applied to the residual
before Rice coding. Real ratios: **Hyser 1.4851×, OTB 2.1934×, CapgMyo 1.3531×,
CEMHSEY 1.9553×**; cost 0.120 (`results/consolidated_bench.csv`). Beats the
prior best (`LMS4+Rice+xchan_bestpartner`, Hyser 1.4804×) on 3 of 4 real sets
(CEMHSEY is a −0.015% dead tie) at 3× the cost — both stay registered as
distinct Pareto points. A cheaper 27-context sibling,
`LMS4bc_lite+Rice+xchan_bestpartner` (cost 0.098), trades a little Hyser/OTB
ratio for a **win on CapgMyo and CEMHSEY** instead — genuinely non-dominated,
not a duplicate (P9). If the bias stage's extra state/compute is unacceptable
on-node, `LMS4+Rice+xchan_bestpartner` (cost 0.039) remains the
minimal-hardware pick, and `LMS4+Rice+xchan_bestpartner_adaptive` is its
zero-side-info streaming realization (ratio within ~0.4%). A third,
cost-efficient corner worth knowing: `LMS4+Rice+xchan_mst` (Chow-Liu spanning
tree spatial front-end, cost 0.046) beats the plain best-partner front-end on
3 of 4 real sets for barely more than its cost (P8).

## Established principles (proven on real HD-sEMG)

### P1 — Cross-channel spatial decorrelation is the dominant lever, bounded by real neighbour correlation.
- **Evidence:** cross-channel gain +10.8% (Hyser) / +17.4% (OTB) / +13.1% (CEMHSEY),
  but **+1.3% on CapgMyo** (differential 8×16 array, neighbour |corr|≈0.29). The
  `+xchan` on/off ablation is worth ~70× every temporal knob.
- **Theory:** a per-channel coder can't remove redundancy that lives *between*
  channels. Reducible bits ≈ the mutual information between a channel and its
  neighbours, which grows with correlation. Where neighbour correlation is low, the
  achievable gain is small *by the physics*, not codec weakness. CapgMyo is the
  honest negative control.
- **Implication:** prioritize spatial mechanisms only where neighbour correlation is
  high. The cross-channel MI splits into **non-interchangeable slices set by array
  scale**: a **global common-mode (CAR)** dominates *tight* arrays (OTB 64-ch: array
  mean CAR ≈ +14.4%) but collapses on large arrays; a **local pairwise** subtract
  dominates *large* arrays (128–320 ch), where shared content is spatially local.
  Match the spatial basis to the redundancy's scale. A **decoder-observable channel
  count** cleanly gates which basis to use with zero side-info (`acar_sel`).

### P1b — A JOINT 2-parent solve recovers a second parent's MI, but selection and count are substitutes set by geometry.
- **Evidence:** a joint co-adaptive 2-tap sign-LMS on both parents got the **highest
  Hyser cross-channel gain of any codec (+12.55%, `jointbp2`)** — the second parent
  genuinely adds MI on the diffuse-local large array — yet stayed **below** a single
  *selected* best-partner on tight OTB.
- **Theory:** a *summed* pair of marginal rank-1 subtracts double-counts the parents'
  shared mode → over-subtracts. A **joint** 2×2 solve (taps co-adapting against the
  shared residual) is the correct fix and works. But on a tight array the local
  pairwise MI is essentially rank-1 (one dominant diagonal neighbour), so a second
  degree of freedom — whether *count* (joint pair) or a *second selected partner* —
  finds little MI and only adds estimation variance. On a large array it's rank≥2, so
  the extra jointly-solved parent finds real MI.
- **Implication:** per-scale winner is settled — **single selected partner on tight
  arrays, jointly-solved best-pair on large arrays.** No single *fixed* front-end wins
  both; a *scale-selected* one is the open lever (frontier #1).

### P2 — Temporal prediction saturates early; deeper prediction *hurts* on real data.
- **Evidence:** order-4 LMS beats order-8 on Hyser and OTB across three independent
  cycles; dropping 8→4 *raised* ratio on all 4 sets **and** cut cost 0.063→0.039
  (the promotion of the current best).
- **Theory:** after a low-order linear predictor the HD-sEMG residual is near-white;
  extra taps fit **noise** (raising coded entropy) while state/compute grow with order.
- **Implication:** keep the temporal predictor **small (order ≤4)**; spend complexity
  on the spatial front-end. Multiplying predictor **coefficient sets** (an activity-
  regime bank, `LMS4rs`) is the same mistake as deeper order — it fragments adaptation
  and fits noise; **spent NEGATIVE, retired.** To lower temporal residual entropy the
  predictor's *functional form* must change (genuinely non-linear), not its tap/set count.

### P3 — For the spatial transform, data-dependent beats data-independent; rank-1 adaptive beats multi-tap.
- **Evidence:** a fixed 45° integer-KLT captured ~half the adaptive single-neighbour
  gain (+8.8% vs +18% OTB); making the KLT angle backward-adaptive was *worse still*
  (+1.7–3.3%, −0.5% CapgMyo). Both retired, dominated on all 4 sets.
- **Theory:** the KLT is optimal only when its basis matches the covariance; a fixed
  45° rotation assumes stationary isotropic equal-variance pairs, violated by real
  anisotropic non-stationary HD-sEMG. A backward-estimated angle is stale/noisy, and a
  Givens rotation is energy-preserving so it corrupts **both** channels — whereas the
  rank-1 subtract injects estimation noise only into the residual and leaves the parent
  clean. The rank-1 adaptive subtract is not just cheaper, it's **more robust** under
  causal estimation noise.
- **Implication:** multi-tap spatial transforms (fixed or adaptive) are a **settled dead
  end** here. The spatial gain lives in the data-dependent pairwise weight.

### P4 — Embeddability is a hard gate; prefer backward-adaptive (zero side-info).
- **Evidence:** the headline `+xchan` beta is a float whole-signal value computed
  offline — **not producible on-node** (see `EMBEDDED_OK_VERIFICATION.md`). Per-block
  backward re-selection of (partner, β) from the previous reconstructed block holds
  the offline ratio within −0.08…−0.41% (and *beats* it on CapgMyo) at **zero side-info,
  look-ahead 0** (`bestpartner_adaptive`).
- **Theory:** anything the decoder can recompute from reconstructed causal history costs
  zero side-info and is streaming-legal; anything from the whole recording trades
  on-node feasibility for ratio. A **slowly-varying** parameter (best-partner identity is
  stable within a recording) costs ~zero ratio to make backward-adaptive.
- **Implication:** prefer backward-adaptive estimation. Treat any offline/whole-signal
  parameter as a realization gap, not a real on-node result — and confirm the streaming
  form's ratio before quoting it as embeddable.

### P5 — Golomb-Rice is at the entropy floor; the entropy back-end is NOT a lever here.
- **Evidence:** a LOCO-ANS-style tANS coder on the identical predictor was **1.4–1.8%
  SMALLER at ~2× cost** on all 4 real sets (retired). Conditioning the Rice *k* on a
  cross-channel energy context (`xctx`) lost 2.3–2.8% — below even plain LMS+Rice (retired).
- **Theory:** Rice is the optimal prefix code for an exactly-geometric residual, and real
  post-LMS HD-sEMG residual blocks are near-geometric — Rice already sits at the floor, so
  there is no sub-Golomb fraction to amortize an ANS table or a context-frequency split.
  After LMS whitening, `H(e_c | cross-channel context) ≈ H(e_c)` — the conditional entropy
  the context meant to exploit was already removed by the predictor.
- **Implication:** the entropy back-end (engine *or* the Rice parameter's context) is a
  **spent, dead lever for ratio**. Lower residual entropy upstream (better decorrelation),
  never at the coder. A back-end swap is justifiable only for throughput/hardware, never ratio.

**Principles P6–P10 below were distilled 2026-08-17 from consolidating five
cycles (2026-08-05 through 2026-08-16) that ran in parallel, blind to each
other, because each was branched from the same unmerged `main`. Where multiple
independent implementations of the same mechanism converged on the same
qualitative result, that convergence is called out explicitly — it is
materially stronger evidence than a single cycle's finding.**

### P6 — Cross-channel MI is instantaneous volume conduction, not a propagating wavefront — settled by 5x independent replication.
- **Evidence:** five *independently implemented* per-block backward-adaptive lag
  searches (different authors' cycles, different search ranges, different tap
  structures) all found lag=0 selected in 92–98% of blocks on every monopolar
  array (Hyser/OTB/CEMHSEY), and all five *lost* ratio there (−0.25% to −1.30%
  vs the zero-lag incumbent). The one consistent exception across all five: the
  CapgMyo *differential* array, where a narrow lag search gains up to +0.9% —
  because the differential electrode has already cancelled the zero-lag common
  mode, so what little MI remains is genuinely non-zero-lag.
- **Theory:** HD-sEMG's dominant neighbour coherence is the shared *far-field*
  volume-conducted signal, which reaches adjacent electrodes effectively in
  phase at these inter-electrode spacings and sample rates — the propagating
  near-field MUAP wavefront every attempt was motivated by is a much smaller
  term. A lag search can only find a delay that is actually there; five
  independent estimators finding lag=0 in >92% of blocks is not a search-space
  or implementation artifact, it is the physics.
- **Implication:** the lag axis is now a **closed, high-confidence dead end**
  for monopolar arrays — do not re-propose without a specific reason a 6th
  attempt would differ. On differential/bipolar arrays it remains a small,
  real, low-priority lever.

### P7 — Backward-search width trades ratio for selection variance ("winner's curse") — the general form of P6's failure mode.
- **Evidence:** every widened per-block backward argmin measured this round —
  the multi-sample lag search (P6), rank-1-vs-rank-2 gating at 3 independent
  granularities (in-sample MDL order selection, a backward rank-statistic
  gate, and a per-channel MDL+hysteresis gate — none beat the better of their
  own two branches, and one landed *below* both), and a radius-expanded
  Chow-Liu spanning tree (P8) — either lost ratio outright or delivered at
  best a statistical tie with the narrower incumbent, even where the wider
  hypothesis class is a **strict superset** (so the true optimum is bounded
  below by the incumbent's).
- **Theory:** a per-block backward selector fits its choice on ~250–2000
  causal samples of the *previous* block only. Enlarging the option set grows
  the selection bias/variance (the empirical-best-of-K systematically
  overestimates the true best as K grows — winner's curse) faster than it
  grows the achievable signal, whenever the true margin between the best and
  next-best option is small relative to single-block estimation noise — the
  common case once a narrow, physically-motivated option set already captures
  most of the real structure.
- **Implication:** before widening any backward-adaptive search, estimate the
  true margin it is chasing (e.g. an oracle/whole-signal upper bound) against
  the single-block estimation-noise floor. Widening a search is a
  **selection-variance cost paid up front for MI that may not exist**, not a
  free strict improvement, even when the option set is a superset.

### P8 — Optimal spatial STRUCTURE (Chow-Liu spanning tree) beats the fixed raster-neighbour set, but the gain is small and array-size-limited.
- **Evidence:** two independently implemented Chow-Liu maximum-weight spanning
  trees over the channel graph (different edge-candidate radii, different
  cost models) both replicate the same qualitative result: a small real gain
  on tight/anisotropic arrays (OTB, 64ch: +0.4–0.8% vs the raster-restricted
  incumbent) that shrinks to roughly zero by 320 channels (CEMHSEY). The
  cheaper implementation (radius-restricted 8-neighbourhood, cost 0.046,
  `LMS4+Rice+xchan_mst`) is registered; the costlier one (0.073, statistically
  the same ratios) is superseded and not carried forward in code.
- **Theory:** Chow-Liu is optimal *given the true* pairwise edge weights, but
  every weight here is estimated from one 256-sample backward block while the
  number of candidate edges grows with array size — so on a large array,
  estimation noise in the edge weights corrupts the greedy max-weight-tree
  construction faster than the freed non-raster edges add real MI (P7's
  mechanism, transposed to the spatial-structure axis). The fixed 4-neighbour
  raster set is, in effect, an accidental regularizer that happens to help
  more than it costs once the array is large.
- **Implication:** structural freedom in the spatial graph is worth pursuing
  only on small/tight arrays (≲64ch); do not extend it to the primary 128ch
  or 320ch arrays without a channel-count gate.

### P9 — Backward-adaptive per-context bias cancellation is the first genuinely positive temporal-axis result since P2/P5 closed order, coefficient-set, and quadratic form.
- **Evidence:** two independently implemented JPEG-LS/CALIC-style running-mean
  bias correctors (27 sign-history contexts vs. 30 quantized-magnitude
  contexts; different authors, different cycles) both beat the pre-cycle
  incumbent on Hyser and OTB, and this is now **the leaderboard best**
  (`LMS4bc+Rice+xchan_bestpartner`, +0.32% Hyser, +1.46% OTB vs the prior
  best, cost 0.120). The cheaper 27-context sibling
  (`LMS4bc_lite+Rice+xchan_bestpartner`, cost 0.098) wins CapgMyo and CEMHSEY
  instead — a genuine, non-dominated cost/context-richness trade-off, not a
  duplicate.
- **Theory:** the sign-sign LMS's constant ±1 update is not MMSE-optimal — its
  fixed point is offset from the Wiener solution, so the post-LMS residual
  retains a small but real context-dependent conditional mean E[e|ctx] that no
  *linear* predictor of any order (P2) can remove. Subtracting a backward
  leaky-mean estimate of that context-conditional mean, entirely divisionless
  and zero side-info, lowers H(e) by the law of total variance
  (H(e) ≥ H(e − E[e|ctx])). This is mechanistically distinct from the retired
  `xctx` (which conditioned the *Rice parameter*, a P5-closed lever, and left
  the residual stream itself untouched) — here the residual stream itself is
  corrected, upstream of the coder.
- **Implication:** the temporal axis has one more live lever after all:
  context granularity/cost of the bias corrector is now the open knob (30 vs
  27 contexts moves cost 22% for a small, real, dataset-dependent ratio
  shift) — worth a follow-up sweep of context definitions before calling it
  closed.

### P10 — Reversing the pipeline (temporal-then-spatial) is conclusively worse than spatial-then-temporal.
- **Evidence:** two independent implementations of the reordered pipeline
  (cross-channel subtract applied to the *post-LMS residual* instead of the
  raw signal, one additionally fixing a genuine scoring-criterion mismatch in
  the incumbent) both lost on every real set at cost identical to the
  incumbent — conclusively Pareto-dominated, both retired.
- **Theory:** the per-channel temporal LMS is spectrally a high-pass filter —
  it removes exactly the shared low-frequency volume-conduction content that
  carries most of the inter-channel mutual information, before the
  cross-channel stage gets a chance to use it. Fixing the (real) scoring
  mismatch in the reordered pipeline did not recover the loss, confirming the
  dominant effect is the pipeline order, not the selection criterion.
- **Implication:** spatial-then-temporal is now a **settled pipeline order** —
  any future refinement to either stage should assume this ordering rather
  than re-litigate it.

---

## Open frontier (ranked by expected payoff/cost)

_Re-ranked 2026-08-17 after consolidating five parallel cycles. Frontier #2
(temporal functional form) is **ACHIEVED** — the bias corrector (P9) is now
the leaderboard best — so it drops off this list. P7's winner's-curse finding
now explains WHY frontier #1 (scale-gating) has repeatedly under-delivered
across three independent attempts (P7); it is re-ranked down accordingly._

1. **Tune the bias corrector's context definition** (P9): the two independently
   discovered context schemes (27 sign-history buckets vs. 30 quantized-magnitude
   buckets) land on genuinely different points of a cost/ratio/per-dataset
   trade-off surface that has not been swept — only two of presumably many
   viable context definitions have been tried. **Highest payoff, lowest
   mechanism risk** — the mechanism is proven, this is a hyperparameter sweep
   on a working lever, not a new bet.
2. **Scale-gate the spatial front-end** (P1b/P8): the payoff ceiling is now
   better understood — P7 shows any backward-selected gate (tried 3 ways at 3
   granularities) tends to land at or below the max of its own branches, so a
   4th gating attempt should budget for a **null or small result**, not assume
   the ceiling is the branches' peak. If pursued, gate `LMS4+Rice+xchan_mst`
   (P8's tight-array winner) against the plain best-partner front-end on
   decoder-observable channel count, matching the already-proven `acar_sel`
   zero-side-info gate discipline (P1/P4) — do not add a 4th learned/estimated
   gate criterion (P7's dead end).
3. **A genuinely non-linear temporal predictor** (P2/P5, unchanged): still the
   only completely untouched axis — P9 added a context-conditioned *additive
   mean* correction, which is a first moment, not a change to the predictor's
   functional form itself. Medium payoff, higher risk, lowest priority of the
   three given #1's low-risk headroom.

## Dead ends — do NOT re-propose (a genuinely different variant must say why)

- **Multi-tap inter-channel transform, fixed or adaptive** (`iklt`, `iklt_adaptive`):
  mismatched/stale basis, corrupts both channels; the rank-1 adaptive subtract dominates (P3).
- **Entropy back-end swap** (`xchan_tans`) and **any context-modeling of the Rice
  parameter** (`xctx`): Rice is at the floor; model side-info is pure loss (P5).
- **Summed multi-parent rank-1 subtract** (`xchan_multiparent`): double-counts the parents'
  shared mode → over-subtracts. The valid multi-parent form is a *joint* solve (P1b), not a sum.
- **Activity-regime / coefficient-set predictor bank** (`LMS4rs`): fragments adaptation, fits
  noise once the residual is white (P2). Same failure as `xctx`, predictor side.
- **Always-on global CAR cascade** (`acar+bestpartner`): superseded by its *scale-gated*
  form `acar_sel` (same tight-array corner, no large-array regression) — always gate a
  geometry-dependent lever on a decoder-observable variable (P1).
- **Time-lagged cross-channel prediction on monopolar arrays**, any implementation
  (P6): closed by 5x independent replication — real neighbour MI is instantaneous
  volume conduction, not a delayed propagating wavefront. Differential/bipolar
  arrays remain a minor, low-priority exception.
- **Widening ANY per-block backward-adaptive search** without first bounding the
  true margin against single-block estimation noise (P7): the general failure mode
  behind P6, the three independent rank-1-vs-rank-2 gating attempts, and the
  radius-expanded spanning tree. A superset option set is not a free win.
- **Temporal-then-spatial pipeline order**, any implementation (P10): the LMS
  high-pass destroys the shared low-frequency mode the cross-channel stage needs,
  confirmed by 2 independent implementations losing on every real set.

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

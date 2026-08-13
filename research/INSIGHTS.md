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

**Best ratio (promoted 2026-08-13):** `LMS4bc+Rice+xchan_bestpartner` — the same
best-partner front-end and adaptive Rice back-end, plus a **context conditional-mean
corrector** after the order-4 LMS. Real ratios: **Hyser 1.4851×, OTB 2.1934×,
CEMHSEY 1.9553×, CapgMyo 1.3531×** (4-set mean 1.7467×, the highest measured here);
cost **0.1202**. Outright max on OTB and CapgMyo of everything benched.

**Best ratio-per-cost / still the codec to port:** `LMS4+Rice+xchan_bestpartner`
(Hyser 1.4804×, OTB 2.1619×, CEMHSEY 1.9555×, CapgMyo 1.3505×; cost **0.039**), or
its streaming form `LMS4+Rice+xchan_bestpartner_adaptive` (per-block re-selection,
zero side-info, within ~0.4%). The promoted best buys +0.32% Hyser / +1.46% OTB for
**3.05× the cost** — almost entirely SRAM (21 KB of context accumulators at 128 ch) —
so it wins the ratio headline but does **not** displace the port pick. Both beat every
embeddable reference (WavPack, mtscomp, even offline zstd-19); only offline LZMA
(1.67× Hyser) is ahead and isn't portable.

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

### P1c — The cross-channel MI is INSTANTANEOUS and LOCAL: the front-end's remaining structural knobs are now measured, and only *which/how many parent* pays.
- **Evidence (2026-08-13, real, 4 sets).** Two structural axes of the rank-1 front-end
  were opened and closed in one cycle.
  *Time offset* (`xlag`, parent taken at a backward-selected lag `d∈0..8`): isolated
  xchan gain **+11.03% Hyser / +14.63% OTB / +1.43% CapgMyo / +12.96% CEMHSEY** — versus
  best-partner's **+11.31 / +18.44 / +1.37 / +13.08%**. The lag axis *shrinks* the lever,
  by **−2.82% on OTB** vs the identical lag-0 codec. **Retired.**
  *Topology* (`xmst`, Chow-Liu max-weight spanning tree over the full 8-neighbourhood,
  replacing the raster-causal best-of-4): isolated gain **+0.359% Hyser, +0.792% OTB,
  −0.010% CapgMyo, −0.042% CEMHSEY**. Real but small, and only on the tight array.
- **Theory.** (i) Tissue volume conduction is **quasi-static**: the far-field potential a
  neighbour shares with a channel arrives at **zero delay**. The propagating MUAP part is a
  minority of the shared variance, and the electrode sums many MUs with different CVs,
  depths and fibre angles, so the neighbour cross-covariance is a *mixture over delays*
  peaking broadly at 0. A single-lag rank-1 operator is **mis-specified** for a mixture;
  the well-specified object is a multi-tap FIR over lags, which P3 already closed. The set
  with the most lag-0 MI (OTB) loses the most from any deviation off `d=0`.
  (ii) The raster-causal parent set discards half the 8-neighbourhood, but that costs
  **≤0.8%** — the local MI field is smooth, so the best *reachable* parent is nearly as
  informative as the best parent. Freeing the topology pays only where the field is
  **anisotropic** (fibre-aligned, tight OTB) and the array is small enough for low-variance
  per-block edge weights; on 128–320 ch it is a wash.
- **Implication:** stop looking for structure in *where in space-time the parent sits*.
  The exploitable slack left in P1 is in *which/how many* parents (P1b) and, per P1, in
  matching the basis scale — not in lag, and only marginally in topology.

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

### P2b — CONFIRMED on real data: changing the predictor's FUNCTIONAL FORM does pay — remove the residual's *conditional mean*, not more of its linear structure.
- **Evidence (2026-08-13, real, `LMS4bc`, promoted best).** An additive JPEG-LS/CALIC-style
  corrector `d[t] = e[t] − μ[c,ctx]` (leaky integer running mean over 30 buckets keyed by
  `q5(e[t−1]) × q3(e[t−2]) × sign(d[parent,t−1])`, shift-divide only) after the *unchanged*
  order-4 sign-sign LMS, with a **bit-identical** front-end and back-end, gained
  **+0.318% Hyser, +1.457% OTB, +0.197% CapgMyo, −0.015% CEMHSEY** — the first **positive**
  temporal-axis result in the log, and enough to take the ratio headline (4-set mean +0.555%).
- **Theory.** `H(e) ≥ H(e − E[e|ctx])`, with equality iff the residual's conditional mean is
  already zero. A *linear* predictor whitens only to second order, and **sign-sign LMS is not
  even MMSE-optimal**: its fixed ±1 step leaves a gradient-noise misadjustment, so during
  amplitude transients the residual carries a **signed, context-persistent bias** the linear
  stage structurally cannot remove. A piecewise-constant (i.e. genuinely non-linear) first-moment
  term removes exactly that, lowering residual variance by `E[μ_ctx²]` ≈ `½log₂(1+E[μ²]/σ²)` bits.
  This is *orthogonal* to P2 (which is about linear capacity) and to P5 (which is about the
  coder): the corrector touches neither tap count, coefficient-set count, nor the Rice model.
- **Where it pays, and why the size ordering holds.** Gain ∝ how far the linear predictor is from
  unbiased: **4.6× larger on OTB (+1.46%) than Hyser (+0.32%)** because OTB VL is the burstiest,
  highest-SNR set (its post-LMS residual is the least white — it also has the largest xchan gain),
  so sign-sign lag during each burst ramp is largest. Flat on 320-ch CEMHSEY (−0.015%): lower
  per-channel SNR and a flatter envelope ⇒ `E[e|ctx] ≈ 0` and the 30 buckets return estimation
  noise. **The corrector's gain is a measure of predictor bias, not of signal redundancy.**
- **Implication:** the temporal axis is **live but second-order** (peak +1.5% vs the spatial
  lever's +18–20%) and it is **paid for in SRAM, not compute**: 120 B/ch of context accumulators
  push cost 0.039 → 0.120 while ops stay inside the 30 kHz budget. Next moves on this axis should
  attack the *bias source* more cheaply (fewer buckets; or a normalized/leaky LMS step that is
  unbiased under transients, removing the need to correct after the fact).

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

### P4b — Backward-adaptive SELECTION has a variance price that scales with the hypothesis space: only widen the search if the extra MI is real.
- **Evidence (2026-08-13, real).** Same backward machinery, same block length (256), three
  different candidate-set sizes. 4 raster parents (`bestpartner_adaptive`) → baseline.
  ~8 scored tree orientations (`xmst`, 2×) → **+0.36…+0.79% on tight/primary, −0.01…−0.04%
  on the large arrays.** ~36 `(parent, lag)` pairs (`xlag`, 9×) → **negative on all four real
  sets, −2.82% on OTB.** Selection width scaled up 2× and 9×; the payoff went from small-positive
  to clearly negative.
- **Theory.** The per-block score is an *estimate* from one stale 256-sample block. Taking the
  argmax over `M` noisy estimates imports a **winner's-curse bias growing like the expected
  maximum of `M` noise terms (≈σ√(2 ln M))**, while the true extra MI available from the wider
  set is whatever the physics actually contains. A wider search is worth it only when the added
  MI exceeds that selection variance — and P1c says the added MI at `d>0` is ~0.
- **Implication:** treat candidate-set width as a *cost*, not a free improvement. Before widening
  a backward search, state where the extra MI comes from; if the answer is "more options", expect
  a loss. Corollary: if a wide search is genuinely needed, lengthen the estimation window or
  re-search every K blocks rather than paying the variance every block.

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

---

## Open frontier (ranked by expected payoff/cost)

*Frontier #2 of the previous cycle (change the predictor's functional form) was SPENT
POSITIVE this cycle and is now principle P2b. The two structural spatial knobs opened this
cycle (lag, topology) are spent — negative and marginal respectively (P1c).*

1. **Make the conditional-mean corrector CHEAP** (P2b + the cost model). The gain is real and
   took the ratio headline, but cost went 0.039 → 0.120 and **~0.082 of that is SRAM** (120 B/ch
   of 30-bucket accumulators), not compute. Shrink the context (the parent-sign bit and the
   `e[t−2]` axis are the least justified — an ablation to ~6–8 buckets is nearly free to run) or
   share `μ` tables across channels within a grid row. Target: ≥70% of the +1.46% OTB gain at
   cost ≤0.06. **Highest payoff, lowest mechanism risk — it converts an already-proven ratio win
   into a portable one, and it is the only path by which the new best can also become the port pick.**
2. **Remove the bias at its source instead of correcting it** (P2b, P2). The corrector exists
   because sign-sign LMS is biased under transients. A **normalized / leaky sign-LMS** (order ≤4,
   step scaled by a backward power estimate) is unbiased under amplitude ramps by construction,
   costs ~0 extra SRAM, and would predict the largest gain on exactly the burstiest set (OTB) where
   the corrector earned +1.46%. Medium payoff, genuinely different axis; if it works it *replaces*
   #1 rather than complementing it — measure both against `LMS4bc` on OTB first.
3. **Scale-select the spatial front-end between the two proven per-scale winners** (P1b): single
   selected best-partner for `C≤64`, jointly-solved best-*pair* for `C≥128`, gated on the
   decoder-observable channel count (`acar_sel`'s proven zero-side-info gate). Still open, still
   the only untried composition inside the dominant lever — but now *stackable* with P2b's
   corrector, which is what would make it clear the best. Note P1c has narrowed what else is left
   here: not lag, and topology is worth ≤0.8% and only on tight anisotropic arrays.

## Dead ends — do NOT re-propose (a genuinely different variant must say why)

- **Multi-tap inter-channel transform, fixed or adaptive** (`iklt`, `iklt_adaptive`):
  mismatched/stale basis, corrupts both channels; the rank-1 adaptive subtract dominates (P3).
- **Entropy back-end swap** (`xchan_tans`) and **any context-modeling of the Rice
  parameter** (`xctx`): Rice is at the floor; model side-info is pure loss (P5).
- **Summed multi-parent rank-1 subtract** (`xchan_multiparent`): double-counts the parents'
  shared mode → over-subtracts. The valid multi-parent form is a *joint* solve (P1b), not a sum.
- **Activity-regime / coefficient-set predictor bank** (`LMS4rs`): fragments adaptation, fits
  noise once the residual is white (P2). Same failure as `xctx`, predictor side.
- **Propagation-delay-aligned (non-zero-lag) cross-channel subtract** (`xchan_lag`): the neighbour
  MI is carried by the **instantaneous, quasi-static volume-conducted far field**, not by the
  propagating MUAP; the true cross-covariance is a broad mixture over delays peaking at 0, so a
  single-lag rank-1 operator is mis-specified, and the 9× wider `(parent,lag)` search pays
  winner's-curse selection variance for MI that isn't there (P1c + P4b). Worse on **all 4** real
  sets than the lag-0 codec it reduces to, at 2.6× the cost, and the only codec to fail `neural_ok`.
- **Always-on global CAR cascade** (`acar+bestpartner`): superseded by its *scale-gated*
  form `acar_sel` (same tight-array corner, no large-array regression) — always gate a
  geometry-dependent lever on a decoder-observable variable (P1).

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

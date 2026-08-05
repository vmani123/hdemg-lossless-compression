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

`LMS4+Rice+xchan_bestpartner` — order-4 sign-sign LMS + adaptive Golomb-Rice, with
a per-channel **best-of-4 causal-neighbour** cross-channel subtract. Real ratios:
**Hyser 1.480×, OTB 2.162×, CEMHSEY 1.956×, CapgMyo 1.350×**; cost 0.039. Beats
every embeddable reference (WavPack, mtscomp, even offline zstd-19); only offline
LZMA (1.67× Hyser) is ahead and isn't portable. If the offline best-partner
*selection* is unacceptable on-node, port `LMS4+Rice+xchan_bestpartner_adaptive`
(re-selects per block, zero side-info, ratio within ~0.4%).

_Unchanged through cycle 16 (2026-08-05): none of `xchan_lagpartner`, `xchan_mdlsel`,
`xchan_post` beat it on real data (P1c, P1d, P6 below). Best embeddable since cycle 7._

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

### P1c — The neighbour MI is INSTANTANEOUS: it is fully measured at lag 0. There is no propagation-delay slice to recover.
- **Evidence (cycle 16, `xchan_lagpartner`, real):** widening the selection domain from
  `{partner}` to `{partner}×{lag}`, τ ∈ [−7, +7], and instrumenting the selector over
  every (channel, block): τ = 0 is chosen in **97.3%** of hyser and **97.6%** of cemhsey
  blocks, and **\|τ\| ≥ 3 in ≤ 8.3%** of blocks on *any* real set — the non-zero mass is
  overwhelmingly ±1 (83% of otb's, 72% of capgmyo's non-zero selections). Ratio:
  hyser 1.4762 (−0.06% vs the zero-lag sibling), otb 2.0559 (**−4.51%**), cemhsey 1.9534
  (−0.03%), capgmyo **1.3575 (+0.34%, the highest capgmyo ratio of any codec or reference)**.
- **Theory:** the predicted `τ* = IED/CV ≈ 3–7 samples @2048 Hz` slice assumes the shared
  component *travels*. It does not: the dominant shared component between surface
  electrodes is the **quasi-static volume-conducted field**, which reaches neighbours with
  no delay, while the travelling depolarization zone carries only a small fraction of the
  shared power at 8–10 mm spacing. So `ρ(τ)` peaks at τ = 0 and P1's zero-lag bound is not
  a measurement artefact — it is the physics. Second, a widened search **costs**: the
  candidate set grows 5 → 29, and the argmin of an *in-sample* score over ~6× more options
  suffers a winner's curse. Crucially, lag is the **least stationary** parameter — a
  phase/delay has a coherence time shorter than the 125 ms selection block, so a τ chosen
  from block *i−1* is stale for block *i* and a misaligned subtract *raises* residual variance.
- **Implication:** τ = 0 is not a limitation to route around; the spatial lever is exhausted
  at zero lag on **monopolar** arrays. The single exception is a **differential/bipolar**
  array (CapgMyo), where the derivation has already cancelled the instantaneous mode
  (\|corr\|(0) ≈ 0.29) so the propagating remainder is all that is left — there a ±1-sample
  lag is the *only* MI available and it pays (+0.35 pp of achieved cross-channel gain,
  1.44% → 1.79%). Gate any lag search on low ρ(0), and keep it to τ ∈ {−1, 0, +1}.

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

### P1d — The spatial model-order selection surface is FLAT: fixing the selector's bias changes the choice a lot and the bits not at all.
- **Evidence (cycle 16, `xchan_mdlsel`, real):** adding the exact MDL/BIC parameter code
  length `(k/2)·log₂B` to `jointbp2`'s in-sample criterion **changed the selected spatial
  order on 7.3% (hyser) / 8.6% (otb) / 25.8% (capgmyo) / 24.2% (cemhsey) of channel-blocks**,
  cutting the k = 2 share by 7–24 pp (cemhsey 64.3% → 40.3%) — the diagnosed over-selection
  bias is real and the correction is large. Ratio moved by **≤ 0.025% in either direction**
  (hyser 1.496743 vs 1.496924, cemhsey 1.952733 vs 1.952260). On the flipped blocks the
  *unpenalized* in-sample gap between the two candidate orders is a **median of 3.0 bits per
  256-sample block — 0.09–0.10% of that block's ~3030 coded bits**.
- **Theory:** the in-sample bias was a **labeling** bias, not a **coding** bias. When the
  second parent carries little MI the joint 2×2 integer LS shrinks its tap toward zero and
  the fixed-point β grid rounds it to exactly 0, so a k = 2 *selection* degenerates to the
  k = 1 *transform* in the emitted stream. What is left is below the **rate granularity of
  the entropy back-end**: Golomb-Rice moves in ~1 bit/sample steps of *k* and cannot spend a
  3-bits-per-block difference. This is P5's floor argument mirrored onto model selection.
- **Implication:** a **visibility bar** for every future front-end refinement — a mechanism
  must change the residual by **≳ 0.1 bit/sample (~25 bits per 256-sample block)** to survive
  the coder that has to express it. Do not spend a cycle on estimator/criterion polish inside
  the existing candidate set; only a mechanism that opens a *new* MI slice can clear the bar.

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
- **Refinement (cycle 16, real): "slowly varying" has a measurable limit — shorter blocks win,
  and a *phase* parameter is not slowly varying at all.** Lengthening the spatial re-selection
  block 256 → 1024 samples costs ratio in **both** cascade domains (raw: hyser −0.47%,
  otb −0.76%, cemhsey −0.56%; innovation: −0.50%, −0.83%, −0.60%), so `(partner, β)` are
  non-stationary at the ~125 ms scale and *more frequent* re-selection is strictly better —
  a longer time constant is not a safe way to buy estimator stability. And per P1c a delay/lag
  parameter's coherence time is *shorter* than one block, so backward selection of it injects
  noise rather than tracking a slow drift. **Backward adaptation is free only for parameters
  whose coherence time exceeds the block; check that before widening a selection domain.**

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

### P6 — Cascade order is settled: SPATIAL first, then temporal. Whitening first destroys the band that carries the neighbour MI.
- **Evidence (cycle 16, `xchan_post`, real):** the same rank-1 estimator moved into the
  *innovation* domain (order-4 LMS first, then the subtract) loses on **all four** real sets
  at **identical** cost 0.03874 — hyser 1.4612 (−1.07% vs its raw-domain twin), otb 2.0801
  (−3.39%), capgmyo 1.3479 (−0.37%), cemhsey 1.9291 (−1.27%) — and retains only **74–89%**
  of the raw-domain achieved cross-channel gain (otb +13.37% vs +17.35%). Confound removed:
  at a matched 256-sample spatial block the reorder alone still loses −0.57% (hyser) /
  −2.58% (otb) / −0.21% (capgmyo) / −0.68% (cemhsey). **Retired.**
- **Theory:** for a fixed β and one shared filter the stages *commute*
  (`A(x_c − βx_p) = A x_c − β·A x_p`), so there was no first-order gain on offer; what breaks
  the commutation is that the LMS whitener is **per-channel adaptive** (`A_c ≠ A_p`), and the
  asymmetry favours spatial-first for two reasons. (i) Subtract first and the temporal
  predictor adapts to *exactly the sequence that is coded*; whiten first and the spatial stage
  is handed two signals already whitened by *different* filters, each having partially removed
  the shared component. (ii) Volume-conducted common mode is **lowpass and high-power** —
  precisely the band the whitener flattens — so `ρ(innovations) < ρ(raw)`. The deficit is
  largest on the highest-coherence array (OTB), the signature of a coherence loss rather than
  an adaptation artefact.
- **Also refuted:** the "difference of two AR processes is higher-order ARMA, so order-4
  under-fits the mixture" argument predicts spatial-first should be *harder* to whiten. It is
  measurably *easier to code*, on all four real sets — consistent with P2 (near-white after
  order 4 either way).
- **Implication:** never reorder the cascade. Any new spatial mechanism goes **before** the
  temporal predictor, on the raw channels.

---

## Open frontier (ranked by expected payoff/cost)

_Refreshed after cycle 16. Three levers were spent this cycle: the **lag/spatiotemporal**
axis (P1c, spent — τ = 0 is the physics), the **selection-criterion / estimator fix**
(P1d, spent — the surface is flat), and the **cascade reorder** (P6, spent NEGATIVE,
retired). The previous #3 (guarantee the large-array branch streams) is **already
satisfied**: `jointbp2`/`mdlsel` are backward-adaptive, zero-side-info, look-ahead 0._

1. **Compose the two measured per-set maxima under the proven zero-side-info scale gate**
   (P1b + P1): `C ≤ 64` → the `acar_sel` CAR-then-best-partner cascade (otb **2.1795**,
   the measured tight-array max), `C ≥ 128` → the jointly-solved best-pair `jointbp2`
   (hyser **1.4969**, the measured large-array max). Every cell is already measured on real
   data, so the projected profile is hyser +1.12%, otb +0.81%, capgmyo −0.01%, cemhsey −0.17%
   vs the current best — **the first construction that clears the best on the primary Hyser
   AND the tight-array OTB simultaneously**, and the first 4-set improvement candidate since
   cycle 7. Both branches and the gate are already verified ⇒ **highest payoff, lowest
   mechanism risk**; cost ≈0.051. Risk: cemhsey stays −0.17% below `bestpartner` (a
   large-array corner the joint pair does not win) — decide in advance whether that is
   acceptable for a promotion, or add a third branch keyed on the same observable.
2. **Narrow-lag partner, τ ∈ {−1, 0, +1}, gated on low ρ(0)** (P1c). The one *positive*
   real-data finding of the lag axis was on the differential array (capgmyo +0.34% over the
   zero-lag sibling, a new max), and ±1 accounts for 72–83% of all non-zero lag selections
   while \|τ\| ≥ 3 is ≤8.3%. Cutting the domain from 29 options to 13 removes most of the
   winner's-curse loss that sank OTB (−4.51%) and drops cost from 0.0775 toward ~0.045.
   Medium payoff (capgmyo is the negative control, so it cannot move the headline), low risk,
   cheap. Do **not** re-open wide-τ search.
3. **Change the predictor's FUNCTIONAL FORM, not its coefficient count** (P2/P5) — now the
   only untouched axis. A linear LMS residual is white *to second order*; any remaining
   compressibility is higher-order. A small sign-of-neighbour or gated-magnitude nonlinearity
   (still order ≤4) is the live temporal lever. **New bar from P1d: it must move the residual
   by ≳0.1 bit/sample (~25 bits per 256-sample block) or it will be invisible to the Rice
   back-end.** Highest mechanism risk; pursue if #1 does not clear the best.

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
- **Innovation-domain / temporal-first cascade** (`xchan_post`, **retired** cycle 16):
  whitening first flattens the lowpass band that carries the volume-conducted neighbour
  coherence, so `ρ(innovations) < ρ(raw)` and the subtract recovers only 74–89% of the gain;
  it also denies the temporal predictor the chance to adapt to the sequence actually coded.
  Dominated at *identical* cost on all 4 real sets (P6). **Spatial always goes first.**
- **Wide integer-lag ("spatiotemporal") partner search** (`xchan_lagpartner`, codec kept
  registered as the non-dominated max-CapgMyo corner — the **lever** is spent): the shared
  field is quasi-static, so ρ(τ) peaks at τ = 0 and a widened selection domain buys winner's
  curse on a parameter whose coherence time is shorter than the block (P1c/P4). Only a
  **τ ∈ {−1,0,+1}** form, gated on low ρ(0), is still worth trying.
- **Polishing the spatial selection criterion inside the existing candidate set**
  (`xchan_mdlsel`, codec kept registered — the **lever** is spent): MDL/BIC penalization
  changes 7–26% of the selected orders and ≤0.025% of the bits, because the selection surface
  is flat at ~3 bits per 256-sample block, below the Rice back-end's rate granularity (P1d).
  Do not re-propose held-out/cross-validated scoring of the same options either.

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

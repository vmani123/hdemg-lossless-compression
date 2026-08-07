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

*Unchanged after cycle 2026-08-07 (3 candidates, 2 retired).* The highest per-set
embeddable ratios now live on non-dominated corners rather than on the headline:
Hyser `jointbp2` 1.4969× / `scalesel` 1.4943×, OTB `acar_sel+bestpartner` 2.1795×,
CapgMyo `scalesel` 1.3525×, CEMHSEY `bestpartner` 1.9555×. No single codec holds all
four — see P1c for why that is now believed to be a ceiling, not a gap.

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
  both. A *scale-selected* one is now measured — see P1c.

### P1c — The per-scale arbitration is SOLVABLE with zero side-info, but it is ratio-neutral: the spatial front-end has hit a shared MI ceiling.
- **Evidence (`xchan_scalesel`, cost 0.0494):** a backward **rank-2-benefit gate**
  (`B2 + B1/128 ≤ B1`, both estimated in Rice bits over the previous reconstructed block)
  picks the right branch on both scales **without the codec ever seeing the channel
  count**: Hyser 1.4943× = **+1.171% over its own rank-1 branch** (`bestpartner_adaptive`
  1.4770×), OTB 2.1530× = **+0.036% over its own rank-2 branch** (`jointbp2` 2.1522×).
  Best CapgMyo ratio of any registered codec (1.3525×). *But* it sits −0.004…−0.175%
  **below the per-set max of its two branches on all four sets**, its 4-set mean is a
  +0.044% tie with the best, and on CEMHSEY it falls −0.033% below **both** branches.
- **Theory:** (a) a gate is a *selector over two estimators*; its achievable entropy is
  `min` over branches **plus** the loss from choosing wrong on some blocks — it can never
  exceed the better branch. (b) The within-recording per-channel rank split it hoped to
  harvest is small because the **neighbourhood covariance rank is near-stationary within a
  recording** (the P4 slowly-varying regime), so a whole-recording choice already captures
  nearly all of it. (c) The CEMHSEY sub-min result exposes **selector/estimator coupling**:
  the rank-2 joint taps must be *frozen* through rank-1 blocks for determinism, so each
  switch resumes adaptation from a stale state and pays a re-convergence transient — a
  "free" backward selector is not free when the branch it gates is itself adaptive.
- **Implication:** the *choice* of spatial front-end is **not** where the remaining bits
  are. Every LMS4 cross-channel codec now sits within **±1.1% on Hyser and ±0.5% on the
  other three real sets** — that spread is a **shared spatial-MI ceiling**, not a mechanism
  gap. Frontier #1 is **spent (resolved, ratio-neutral)**. Do not propose further
  arbitration/gating among already-measured spatial front-ends; only a front-end that
  reaches redundancy *none* of them addresses can move the number.

### P1d — The spatial parent lives at LAG 0; widening the backward argmin costs selection variance, and that cost is paid where the MI margin is flattest.
- **Evidence (`xchan_lagbp`, cost 0.0706):** adding a propagation-lag axis `d ∈ [0..8]` to the
  proven per-block best-partner argmin (rank stays 1, back-end unchanged — the only variable is
  the search grid) **lost on all 4 real sets vs. the identical lag-0 codec**
  `bestpartner_adaptive`: otb 2.0923× vs 2.1531× (**−2.825%**), hyser 1.4767× vs 1.4770×,
  capgmyo 1.3513× vs 1.3529× (**−0.113%**), cemhsey 1.9534× vs 1.9539×. Retired. The candidate's
  own pre-registered falsification criterion — *"largest gain expected on CapgMyo"* — **fired**.
  (A synthetic propagating-source probe confirms the machinery works and recovers true delays with
  β ≈ 1.0, so this is a data fact, not a bug: mechanism-illustration only.)
- **Theory, two layers.** (1) **The lag has nowhere to go.** At 1–2 kHz sampling with 4–10 mm
  inter-electrode spacing and 3–5 m/s conduction velocity, the true inter-electrode delay is
  **~0.5–2% of a sample period** — sub-sample. `I(x_g[t]; x_p[t−d])` peaks at `d = 0` and falls
  monotonically for `d ≥ 1`; the delayed replica is *not resolvable on this sampling grid*.
  CapgMyo, the slowest-sampled set (1 kHz), inverted the prediction hardest — exactly as this
  predicts. (2) **A wider argmin over the same block is a worse estimator.** The option count grew
  ~9× (4 partners → 36 `(p,d)` pairs) with the block length unchanged, so the argmin more often
  picks the *winner by noise*, which is then applied to the **next** block where the noise does not
  repeat — textbook selection overfitting / winner's curse. The loss scales **inversely with the MI
  margin** between the true best option and its runners-up, which is why the tight, near-rank-1
  64-ch OTB array (P1b) is hurt worst.
- **Implication:** backward selection is cheap in *side-info* but not in *statistics* — **only widen
  a backward option set when the added options carry MI comparable to the incumbent's margin**, and
  budget the block length against the option count. The lag axis is **spent NEGATIVE** at ≤2 kHz;
  the only theoretically live version is a *fractional*-delay (interpolating) parent, which breaks
  integer-only losslessness.

### P2 — Temporal prediction saturates early; deeper prediction *hurts* on real data.
- **Evidence:** order-4 LMS beats order-8 on Hyser and OTB across three independent
  cycles; dropping 8→4 *raised* ratio on all 4 sets **and** cut cost 0.063→0.039
  (the promotion of the current best).
- **Theory:** after a low-order linear predictor the HD-sEMG residual is near-white;
  extra taps fit **noise** (raising coded entropy) while state/compute grow with order.
- **Implication:** keep the temporal predictor **small (order ≤4)**; spend complexity
  on the spatial front-end. Multiplying predictor **coefficient sets** (an activity-
  regime bank, `LMS4rs`) is the same mistake as deeper order — it fragments adaptation
  and fits noise; **spent NEGATIVE, retired.**

### P2b — The temporal lever is closed over FORM as well as over order and set count: HD-sEMG has no higher-order temporal redundancy to remove.
- **Evidence (`LMS4v2`, cost 0.0592):** a degree-2 **Volterra** basis (`x²[t−1]`,
  `x[t−1]x[t−2]`, `x²[t−2]`) added to the *same single* order-4 sign-sign LMS loop, with the
  *identical* best-partner front-end (a clean single-variable A/B), **lost on all 4 real sets
  and both synthetic sets**: hyser 1.4758× vs 1.4804× (−0.310%), otb 2.1431× vs 2.1619×
  (−0.870%), capgmyo 1.3468× vs 1.3505×, cemhsey 1.9521× vs 1.9555×. Retired. The achieved
  xchan gain dropped on every set (otb +17.41% vs +18.44%) — the `LMS4rs` fingerprint: a worse
  temporal residual feeds the unchanged spatial stage.
- **Theory, two layers.** (1) **No signal to fit.** Surface HD-sEMG is a *linear*
  volume-conductor filtering of superimposed MUAPs — a linear, passive, ~time-invariant
  medium driven by a near-symmetric excitation ⇒ the process has a **vanishing bispectrum**,
  so the third-order moments the quadratic taps estimate, `E[e_t·x_{t−i}x_{t−j}] ≈ 0`. The
  sign-sign gradient is pure noise. This is *stronger* than P2's original claim: the residual
  is white after order-4 LMS not merely empirically-to-second-order but because the **source
  process is genuinely linear**, so there is no higher-order redundancy at *any* degree.
  (2) **A zero-mean gradient still costs bits.** The quadratic taps random-walk about 0; their
  contribution is a zero-mean `O(x)`-variance disturbance *added* to the residual, and adding
  an independent zero-mean term strictly raises variance and hence Rice-coded length.
  **Estimating a parameter whose true value is zero is never free** — the estimator's variance
  is paid in coded bits. Same accounting as retired `xctx` (P5) and `LMS4rs` (P2), now shown on
  the predictor's *basis*.
- **Implication:** the temporal lever is exhausted on all three axes — **order**, **coefficient-set
  count**, **basis functional form**. Do not propose non-linear temporal predictors (Volterra,
  gated-magnitude, sign-of-neighbour, NN-flavoured) on this signal. Frontier #2 **spent NEGATIVE**.
  A self-disabling design (leak-to-zero) is still the right hygiene: it bounded the damage to
  −0.2…−0.9% instead of divergence and made the result a clean falsification.

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

---

## Open frontier (ranked by expected payoff/cost)

**Status after cycle 2026-08-07: the two headline frontiers are SPENT.** #1 (scale-select the
spatial front-end) was *resolved* — the rank gate works mechanically at zero side-info but is
ratio-neutral (P1c). #2 (change the predictor's functional form) was *falsified* — the source is
linear, so there is no higher-order temporal redundancy (P2b). Three levers are now measured and
closed on the *same* underlying finding: **`LMS4 + Rice + any rank-≤2 lag-0 spatial front-end`
sits on a shared MI ceiling** — all 6 registered variants land within ±1.1% on Hyser and ±0.5%
elsewhere. Ratio progress now requires reaching redundancy **none** of them addresses.

1. **Non-local / long-range spatial parents** (P1 + P1c + P1d). Every measured front-end draws its
   parent from the **≤4 immediately-causal grid neighbours** — the ceiling in P1c may be the
   *neighbourhood's* ceiling, not the array's. Motor-unit territories span 5–10 mm and a single MU
   fires on **many, non-adjacent** electrodes, so `I(x_c; x_p)` for a distant same-territory channel
   can rival an adjacent one. Test: keep rank 1 and the proven backward per-block argmin, but widen
   the *candidate pool* from the 4 grid neighbours to a small set of **distant causal channels**
   (e.g. same column ±2 rows, or a fixed decimated stride). **Must respect P1d**: keep the option
   count small (≤8) relative to the block, or lengthen the block, so the added options are not paid
   for in selection variance. Highest remaining payoff; directly attacks the P1c ceiling; mechanism
   risk medium.
2. **Exploit the array's non-stationarity in TIME rather than in space** (P4 + P1c(c)). All spatial
   parameters are re-selected per 256-sample block, but the *rate* has never been a variable, and
   P1c showed the selector/estimator coupling (tap-freeze transients) actually **costs** ratio.
   Test: hold the front-end fixed and vary only the re-selection block length / add hysteresis to the
   partner decision, so a stable parent stops re-paying estimation noise. Cheap, low-risk, low-payoff
   (expect ≤0.5%) — but it is the one knob that *reduces* estimator variance rather than adding DOF,
   which is the direction every negative result this cycle points to.
3. **Close the LZMA gap where it is real, not where it isn't** (sanity anchors). Offline LZMA still
   beats every embeddable codec on Hyser (1.67× vs 1.497×) and CEMHSEY (2.06× vs 1.956×) but *loses*
   on OTB and CapgMyo. LZMA's advantage is **long-range repeated literals across the whole
   recording**, a form of redundancy no order-4 predictor + memoryless Rice coder can see. Test
   first as a *diagnostic*, not a codec: measure how much of LZMA's Hyser margin survives on the
   **post-LMS4+xchan residual stream**. If ~none, the gap is quantization/packing overhead and the
   frontier is closed; if a lot, a bounded-window match/repeat stage is the next real lever.
   Diagnostic cost is low and it is the only measurement that can tell us whether ~1.5× is the
   embeddable ceiling on Hyser.

## Dead ends — do NOT re-propose (a genuinely different variant must say why)

- **Multi-tap inter-channel transform, fixed or adaptive** (`iklt`, `iklt_adaptive`):
  mismatched/stale basis, corrupts both channels; the rank-1 adaptive subtract dominates (P3).
- **Entropy back-end swap** (`xchan_tans`) and **any context-modeling of the Rice
  parameter** (`xctx`): Rice is at the floor; model side-info is pure loss (P5).
- **Summed multi-parent rank-1 subtract** (`xchan_multiparent`): double-counts the parents'
  shared mode → over-subtracts. The valid multi-parent form is a *joint* solve (P1b), not a sum.
- **Activity-regime / coefficient-set predictor bank** (`LMS4rs`): fragments adaptation, fits
  noise once the residual is white (P2). Same failure as `xctx`, predictor side.
- **Non-linear temporal predictor of any degree** (`LMS4v2`, degree-2 Volterra): surface EMG is a
  *linear* volume-conductor process, so its bispectrum vanishes and the higher-order moments such a
  predictor estimates are ≈0 — zero-mean gradient, non-zero estimator variance, paid in coded bits.
  Lost on all 4 real sets at 1.5× cost (P2b). Closes the temporal lever over *basis form*, not just
  order/set count.
- **Propagation-lag-aligned spatial parent** (`xchan_lagbp`): the true inter-electrode delay is
  **sub-sample** at ≤2 kHz, so `I(x_g[t]; x_p[t−d])` peaks at `d=0`; a 9× wider backward argmin over
  the same block buys no MI and adds selection variance, worst on tight near-rank-1 arrays (−2.8%
  OTB) (P1d). A fractional-delay parent is the only live variant and breaks integer losslessness.
- **Further arbitration/gating among the already-measured spatial front-ends** (`xchan_scalesel`
  resolved this): a selector cannot exceed the max of its branches, the neighbourhood rank is
  near-stationary within a recording, and gating an *adaptive* branch costs a tap-freeze transient
  (P1c). A new front-end must reach redundancy the existing ones don't see, not re-mix them.
- **Always-on global CAR cascade** (`acar+bestpartner`): superseded by its *scale-gated*
  form `acar_sel` (same tight-array corner, no large-array regression) — always gate a
  geometry-dependent lever on a decoder-observable variable (P1).

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

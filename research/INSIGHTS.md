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

`LMS4bc+Rice+xchan_bestpartner` (promoted 2026-08-10) — order-4 sign-sign LMS +
per-channel **best-of-4 causal-neighbour** cross-channel subtract + a **JPEG-LS-style
context-conditioned integer bias corrector** before adaptive Golomb-Rice. Real ratios:
**Hyser 1.4835×, OTB 2.1804×, CEMHSEY 1.9700×, CapgMyo 1.3538×**; cost 0.098. It beat
the previous best (`LMS4+Rice+xchan_bestpartner`, 1.4804 / 2.1619 / 1.9555 / 1.3505,
cost 0.039) on **all four** real sets, +0.21…+0.85%, mean +0.51%. Beats every embeddable
reference (WavPack, mtscomp, even offline zstd-19); only offline LZMA (1.67× Hyser) is
ahead and isn't portable. The cheap predecessor is **not** retired — higher ratio at
higher cost means both stay on the front, and it remains the value/port-economy pick.
**Port caveat (inherited, unchanged):** both sit on the *offline whole-signal*
best-partner selection + β. The streaming front-end is
`LMS4+Rice+xchan_bestpartner_adaptive` (per-block backward re-selection, zero side-info,
within ~0.4%); the bias stage itself is already zero-side-info and look-ahead 0, but the
**stack of the two is not yet measured** — see open frontier #1.

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

### P1a — The cross-channel MI is carried by the INSTANTANEOUS (zero-lag) field, not by the travelling wavefront. The lag axis is dead.
- **Evidence (2026-08-10, `xlag`):** a propagation-aware front-end — per-block backward
  correlogram search over (parent, τ ∈ [−7..+7]) + an MPEG-4-ALS-MCC 3-tap cross-filter,
  which reduces *exactly* to `bestpartner_adaptive` at τ≡0 — measured against that exact
  τ=0 control: **Hyser −0.58%, OTB −5.75%, CEMHSEY −0.08%, CapgMyo +0.81%** (mean −1.40%).
  Achieved cross-channel gain fell from +18.4% to +11.2% on OTB. The *only* real gain was
  on **CapgMyo, the set predicted before measurement to be the negative control**.
- **Theory:** the hypothesis (ρ(τ\*) ≥ ρ(0), so reducible bits −½log₂(1−ρ²) can only grow)
  is true for a *pure* travelling wave and false for what electrodes actually see. HD-sEMG
  neighbour redundancy is dominated by **volume conduction** — a quasi-static resistive
  field, hence **zero-lag by construction** — plus a global common mode; the propagating
  MUAP is a minority of the shared variance. Shifting the parent by τ *destroys* alignment
  with the large instantaneous component to chase the small travelling one. OTB proves it
  directly: the array where the zero-lag global mode is worth the most (`acar` +14.4%) is
  where the lag search loses the most. Two estimator failures compound it: (i) τ\* is **not
  slowly varying** — it is only defined while a MUAP traverses, and firing is a point
  process, so P4's cheap-backward-adaptation condition (which holds for partner identity
  and β) fails; (ii) arg-max over up to 60 sign-free hypotheses with no MDL penalty is
  upward-biased on a flat ρ(τ) surface, so a spurious τ≠0 wins whenever the true surface
  is flat.
- **Implication:** **do not re-propose a time-lag / propagation axis** for the spatial
  front-end. Corollary worth remembering: the lag lever pays only where the *zero-lag*
  lever is already empty (CapgMyo's differential montage cancels the instantaneous common
  mode), i.e. it is a substitute for zero-lag MI, never an addition to it.

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
  both — but the *adaptive-selection* repair is now measured and spent (P1c).

### P1c — Adaptively SELECTING between two near-equal hypotheses loses to committing to either. Spatial model order is not measurable per block.
- **Evidence (2026-08-10, `bprank`):** a per-channel, per-block backward code-length gate
  between the rank-1 (`bestpartner_adaptive`) and jointly-solved rank-2 (`jointbp2`)
  hypotheses, with a BIC penalty and hysteresis, zero side-info. It landed **below BOTH
  of its own branches on 3 of 4 real sets** (vs rank-1: −0.16% OTB, −0.10% CapgMyo, −0.10%
  CEMHSEY; vs rank-2: −0.11% Hyser, −0.12% OTB, −0.01% CEMHSEY), for +18% cost
  (0.055 vs 0.047). It reproduced `jointbp2`'s answer to within ±0.12% everywhere.
- **Theory:** "expected code length of a selector ≤ min over the fixed classes" holds for
  an *oracle*. This selector is **backward** — it scores both hypotheses on block *k−1*
  and commits for block *k*. On real HD-sEMG the two hypotheses' true code lengths differ
  by only 0.04–1.2%, which is **below the per-block estimation noise of the score**, so
  the decisions are noise and the classic model-selection variance penalty exceeds the
  gain. The MDL term (4 bits/block/channel at B=256) is orders of magnitude too coarse to
  arbitrate a margin of ~10⁻³ of the block's bits, and the anti-chatter hysteresis also
  freezes wrong decisions. Note the worst case is **OTB**, the tight array where P1b says
  rank-1 should win — precisely because the margin there is smallest.
- **Implication:** gate a front-end only on a variable that is **structural and observed
  without estimation** (channel count, grid position — `acar_sel` works for exactly this
  reason), never on an *estimated* code-length margin that is smaller than its own
  estimator's variance. Frontier #1 (adaptive rank/selection gate) is **spent ≈0/negative**.

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
  predictor's *functional form* must change (genuinely non-linear), not its tap/set count
  — **and as of 2026-08-10 that prediction is confirmed: see P6.**

### P6 — A context-conditioned integer BIAS corrector on the prediction is the one live non-linear lever. LMS saturation is a property of the LINEAR class only.
- **Evidence (2026-08-10, `LMS4bc`, PROMOTED):** inserting a JPEG-LS/LOCO-I bias stage
  between the order-4 LMS and the Rice coder — `ctx = (sgn e[t−1], sgn e[t−2], sgn
  e[parent,t])`, 27 contexts/channel, divisionless (B/N counters halved by shift, C nudged
  ±1, clamped int8) — with the cross-channel front-end, the LMS pass and the entropy coder
  **byte-identical to the incumbent**, gained **Hyser +0.213%, OTB +0.854%, CapgMyo
  +0.244%, CEMHSEY +0.739%** (mean +0.51%). First candidate since cycle 7 to beat the best
  on **all four** real sets. Achieved cross-channel gain rose to **+11.5 / +19.5 / +1.6 /
  +13.9%** — the highest of any registered codec on OTB and CEMHSEY.
- **Theory:** an LMS filter zeroes *linear* correlation; it does **not** zero
  `E[e_t | f(history)]` for non-linear `f`. Any surviving conditional mean is
  first-order-removable structure that **no linear predictor of any order can represent**,
  and by the law of total variance removing it lowers residual variance by exactly
  `Var(E[e|ctx])` ⇒ shorter Rice codes. Physically: MUAPs are asymmetric biphasic and
  firing is bursty, so residual **sign-runs** carry a non-zero conditional mean, and the
  non-normalised *sign-sign* update lags during amplitude transients, leaving a
  context-dependent DC. The gain's **shape** confirms the mechanism: it is largest exactly
  where the cross-channel structure is strongest (OTB +0.85%, CEMHSEY +0.74%), because the
  third context bit is the **sign of the co-located parent residual** — β is a single
  scalar per channel-block, hence a *symmetric* linear map, while `E[e_c | sgn e_parent]`
  is an **asymmetric, sign-dependent** offset. The corrector therefore harvests a slice of
  `H(e)` that survives *both* the linear temporal filter and the linear spatial subtract.
- **Why this is not `LMS4rs` or `xctx` (both retired), and the distinction generalises:**
  `LMS4rs` forked whole 4-tap *coefficient sets* per regime, splitting the adaptation data
  so every estimate got noisier (P2's failure); here a **scalar mean per context** is
  estimated — orders of magnitude fewer samples to converge. `xctx` conditioned the Rice
  *parameter*, the back-end lever P5 declared spent, leaving the residual untouched; this
  changes the **residual stream itself**, the upstream place P5 directs spending. The rule:
  **condition a low-order statistic (a mean) upstream, never a high-order model or the
  code parameter.**
- **Cost caveat:** +8 ops/sample-ch is cheap, but 141 B/ch of context state (18.0 KB at
  128 ch) drives cost 0.098 vs 0.039 — so the new best does **not** dominate its
  predecessor. Shrinking the context alphabet is a pure-cost, ratio-neutral-to-positive win.

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

## Open frontier (ranked by expected payoff/cost) — re-ranked 2026-08-10

The 2026-08-10 cycle **spent two levers and opened one**: the spatial lag axis is dead
(P1a), the adaptive rank/selection gate is dead (P1c), and the non-linear
functional-form lever (old #2) **paid and is now the promoted best** (P6). The frontier
now points *along* P6, not away from it.

1. **Stack the bias corrector on the STREAMING front-end** (P6 × P4). `LMS4bc` sits on
   the *offline* `_bp_select`, so the promoted 1.4835×/2.1804× is not an on-node number.
   The bias stage is already zero-side-info and look-ahead 0, and `bestpartner_adaptive`
   holds the offline ratio within ~0.4% — so `LMS4bc_adaptive` should hold ≈1.479/2.171.
   **Highest payoff, near-zero mechanism risk**: it converts the new best from a ratio
   claim into a portable one, and it is the only thing standing between the leaderboard
   and an honest on-node headline. Not a ratio play; an embeddability guarantee.
2. **Tune the bias context — richer where it paid, cheaper where it didn't** (P6). The
   gain concentrated on the sets with the strongest cross-channel structure, and the third
   context bit is the parent-residual sign — so widen the *spatial* axis (2 parents' signs,
   or a 3-level quantised parent residual) and shrink the *temporal* axis (drop `sgn
   e[t−2]`) at constant or lower table size. This is also the only route to pull cost
   0.098 back toward 0.04, which is what currently stops the new best from Pareto-
   dominating its predecessor. Medium payoff, low risk, directly cost-relevant.
   **Guard-rail from P1c:** keep the context *structural* (fixed alphabet, always-on
   counters) — do not turn it into an estimated per-block model-selection gate.
3. **Second-order (magnitude) bias context, not just sign** (P6 → P2). If `E[e|ctx]` is
   non-trivial, so may be `E[e | quantised |e[t−1]|]` — a gated-magnitude non-linearity,
   still order ≤4 and still a scalar-mean estimate per bucket. Genuinely different axis
   from #2, higher risk; pursue only if #2's spatial widening saturates.

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
- **Time-lagged / propagation-aware cross-channel prediction** (`xlag`, 2026-08-10): the
  shared field is instantaneous volume conduction, so a τ-shifted parent is a **basis
  mismatch**, not a richer basis; and τ\* is not slowly varying, so it cannot be
  backward-estimated (P1a). Measured −5.75% on OTB against its own τ=0 reduction. *The
  codec itself is kept registered — it is the strict max-ratio corner on CapgMyo (1.3638×)
  — but the **lever** is dead: do not re-propose a lag axis, an MFCV-style correlogram, or
  a multi-tap temporal cross-filter on a parent.* It also **fails `neural_ok`** (154 > 125
  cyc/sample-ch), the first registered codec to do so.
- **Backward per-block gating between two near-equal spatial hypotheses** (`bprank`,
  2026-08-10): the decision margin is smaller than the estimator's own variance, so the
  selector lands *below both* fixed branches (P1c). Kept registered (a +0.087% CapgMyo
  edge over `jointbp2` is its only non-dominated point; first retirement candidate next
  cycle), but the mechanism is spent. Gate on structure (channel count, grid position),
  never on an estimated code-length margin.

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×** (cycle 2026-08-10 max: 2.1804×,
  otb, `LMS4bc`). Any lossless ratio **> ~6×** on realistic broadband ⇒ a leak or
  degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

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

**Unchanged after cycle 2026-08-16**, which attacked the three remaining unexamined
assumptions of the pairwise edge — its *lag* (`xlag`), its *domain* (`xres`), its
*graph* (`xtree`) — and found two of the three spent negative and the third (`xtree`)
a genuine but **array-size-limited** structural gain. See P6/P7/P8.

**The temporal-only null for this family**, measured directly on real data at 15 000
samples (order-4 sign-sign LMS + adaptive Rice, no cross-channel stage, 12 B header) —
use it to isolate any future front-end's *achieved* gain rather than quoting a ceiling:
**Hyser 1.3321×, OTB 1.8347×, CapgMyo 1.3336×, CEMHSEY 1.7280×.**

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

### P6 — The spatial edge's LAG is not a lever: enlarging the per-block hypothesis space costs more in selection variance than the extra alignment buys.
- **Evidence (2026-08-16, `xlag`, `results/cycle_bench.csv` + isolated-gain run):**
  searching `(parent, delay d∈[0,8])` instead of `(parent)` — a **strict superset** of the
  incumbent's option set, same predictor, same back-end — *lost* achieved cross-channel gain
  on the three sets that have spatial MI: OTB **+11.24% vs +17.36%** (−6.1 pp), Hyser
  +10.55% vs +10.88%, CEMHSEY +12.95% vs +13.07% (peer = `bestpartner_adaptive`). Real
  ratios: OTB 2.0409× (−5.60% vs best), Hyser 1.4727× (−0.52%). It gained only on the
  **negative control**, CapgMyo (+1.82% vs +1.45%, its one non-dominated corner).
- **Theory:** a superset can only shorten the code *given the true statistics*; the codec
  instead maximizes an **empirical** Rice length over ≤72 options fitted on 248 samples and
  applies the argmin to the *next* block. Selection bias grows like the log of the
  hypothesis-set size while the sample budget is fixed, so the generalization gap swamps the
  extra alignment. Physically the premise was also weak: MUAP conduction delay is real, but
  after the volume-conduction low-pass the neighbour cross-spectrum's dominant term is the
  **zero-phase** shared mode, not the linear-phase propagating one — `ρ_cp(0)` is already
  near `max_d ρ_cp(d)`. Where lag-0 correlation is genuinely weak (CapgMyo, |corr|≈0.29) the
  incumbent's estimate is itself near-noise and the extra freedom is not a net loss.
- **Implication:** **do not spend degrees of freedom on the backward selection search.** The
  per-block estimator, not the model class, is the binding constraint on the spatial
  front-end. Any new spatial lever must either keep the option set ≤ the incumbent's or pay
  for its enlargement with more samples per decision (bigger block, or pooling across time).

### P7 — Stage ORDER dominates estimator matching: the cross-channel subtract must come BEFORE the temporal predictor, because the predictor destroys the redundancy it would exploit.
- **Evidence (2026-08-16, `xres`, retired):** running the order-4 LMS first and fitting +
  scoring the rank-1 subtract on the **temporal residuals** — everything else held verbatim
  (same candidate set, same integer-LS gain, same `_bpa_select_block`, same back-end, same
  cost 0.038743) — lowered the achieved cross-channel gain on **every** real set:
  OTB **+14.32% vs +17.36%** (−3.04 pp), Hyser +10.25% vs +10.88%, CEMHSEY +12.31% vs
  +13.07%, CapgMyo +1.23% vs +1.45%. Ratios worse on all 4 at identical cost → retired.
- **Theory:** the order-4 sign-sign LMS is spectrally a per-channel **high-pass** — it
  removes each channel's predictable low-frequency content. That shared low-frequency
  volume-conduction mode is exactly where the inter-channel mutual information lives, so
  `ρ_e ≪ ρ_x` and `I(e_c ; e_p) ≪ I(x_c ; x_p)`. Temporal whitening and spatial
  decorrelation **do not commute**, and the redundancy is destroyed by whichever runs first.
  The motivating criterion-mismatch argument (scored quantity should equal coded quantity)
  is *correct* — but it is a second-order estimator refinement applied to a first-order
  worse-conditioned signal. The gap tracks the size of the shared mode: largest on OTB
  (−3.04 pp, where the raw-domain gain was largest) and ≈0 on CapgMyo (−0.22 pp, no shared
  mode to lose).
- **Implication:** **spatial-then-temporal is the correct pipeline order and is now settled.**
  Fit spatial weights in the domain where the MI still exists (raw), not where the bits are
  emitted. More generally: when a refinement changes both an estimator and the signal it
  operates on, attribute the operator order first.

### P8 — Optimal spatial STRUCTURE (Chow–Liu tree) beats the raster-causal set, but the gain decays with array size and reverses by C≈320: the fixed 4-neighbour set is an accidental regularizer.
- **Evidence (2026-08-16, `xtree`, kept, not promoted):** a backward-derived maximum-weight
  spanning forest over a radius-restricted edge set, coded in topological order (zero
  side-info, 30.3% of chosen edges have parent index > child — structurally impossible under
  `_bp_candidates`), vs its exact peer `bestpartner_adaptive`, achieved cross-channel gain:
  **C=64 OTB +18.32% vs +17.36% (+0.96 pp — the highest OTB xchan gain of ANY codec)**;
  C=128 Hyser +11.27% vs +10.88% (+0.39 pp); C=128 CapgMyo +1.43% vs +1.45% (−0.02 pp,
  negative control); **C=320 CEMHSEY +13.01% vs +13.07% (−0.06 pp)**. Monotone in C.
- **Theory:** Chow–Liu is optimal *given the true* edge MIs — among first-order dependency
  structures the max-weight spanning tree minimizes KL to the joint, and for Gaussians the
  edge weight `−½log₂(1−ρ²)` **is** the rank-1 coding gain. The theorem prices no estimation
  cost. Here every weight is estimated from one fixed 256-sample block while the number of
  edges ranked grows as ≈5C: ~1.25 edges/sample at C=64, ~6.25 at C=320. Greedy Kruskal then
  *locks noise in as global structure* — a spuriously high-weight edge does not waste one
  channel, it displaces an entire subtree. So the incumbent's 4 raster-causal neighbours are
  a strong **structural prior**: a little bias (it forbids the right/down half and starves
  boundary channels) bought with a large variance reduction, and that trade turns favourable
  precisely as C grows. This is P2's "extra freedom fits noise" transposed from the temporal
  axis to the spatial-structure axis, and it is the same bias–variance ledger as P6.
- **Implication:** structural freedom in the spatial graph is worth **~+1 pp of xchan gain on
  tight arrays only**. The correct construction is not "tree everywhere" but a **tree gated
  on the decoder-observable channel count** (`C ≤ 64` → tree, `C ≥ 128` → raster
  best-partner) — the identical zero-side-info gate `acar_sel` already proved (P1). Note
  this makes **three independent levers that all want the tight-array branch** (CAR cascade,
  spanning tree) versus the large-array branch (joint 2-parent) — array scale is the single
  most predictive covariate in this problem.

---

## Open frontier (ranked by expected payoff/cost)

_Re-ranked 2026-08-16. Three levers were spent this cycle: the edge's **lag** (P6, negative),
its **domain** (P7, negative, retired), its **graph** (P8, positive but C-limited). The
surviving pattern across P1/P1b/P8 is that **array scale**, not mechanism novelty, selects
the winner — so the top of the frontier is now explicitly about gating, and the estimator's
sample budget (P6/P8) is the newly-identified binding constraint._

1. **Scale-gate the spatial STRUCTURE: `xtree` for `C≤64`, raster `bestpartner` for `C≥128`**
   (P8 + P1's proven zero-side-info channel-count gate). `xtree` measured +0.96 pp of
   cross-channel gain on 64-ch OTB (2.1707×, +0.41% vs best) and −0.06 pp on 320-ch CEMHSEY;
   the gate is arithmetic on already-measured numbers and both branches are already
   bit-exact-verified. Would give OTB ≈2.1707× while *exactly* preserving the incumbent's
   Hyser/CapgMyo/CEMHSEY ratios — the first construction with **no real-set regression at
   all**. Also drops the tree cost on the large arrays where it never pays (0.0733 → 0.0394),
   so the gated codec is cheaper on average than `xtree`. **Highest payoff, lowest mechanism
   risk.** Risk: still only +0.41% on one set → likely a kept non-dominated corner, not a
   headline promotion; and it stacks awkwardly with `acar_sel`, which already owns the OTB
   corner at 2.1795× for cost 0.043 — measure *both* gates composed before claiming anything.
2. **Widen the backward estimator's sample budget instead of the model class** (P6/P8 —
   the newly-identified binding constraint). Every recent loss was selection variance, not
   model capacity: `xlag` (≤72 options / 248 samples), `xtree` at C=320 (~1600 edges / 256
   samples). Cheap fixes that add **zero** model freedom: (a) exponentially-weighted edge
   statistics pooled across blocks (leaky accumulators, one per candidate edge — the state is
   already allocated in `xtree`) so each decision sees an effective window of ~1–2 k samples;
   (b) hysteresis / switch-cost on re-selection so a partner only changes when the estimated
   saving beats the incumbent by a margin. Best-partner identity is *slowly varying* (P4), so
   this should be near-free in ratio and strictly reduce variance. Retrofit onto
   `bestpartner_adaptive` first — a clean single-variable test of the P6/P8 thesis.
   **Medium-high payoff, genuinely new axis, low cost.**
3. **Change the predictor's FUNCTIONAL FORM, not its coefficient count** (P2/P5). A
   linear LMS residual is white *to second order*; any remaining compressibility is
   higher-order. A small sign-of-neighbour or gated-magnitude nonlinearity (still order
   ≤4) is the only live temporal lever. Medium payoff, genuinely different axis, higher risk.
   Unchanged in rank relative to the spatial levers, but now the only *untouched* axis left —
   the pairwise spatial edge is fully explored in lag, domain and graph.
4. **Scale-select between best-partner (`C≤64`) and jointly-solved best-pair (`C≥128`)**
   (P1b) — the literal old frontier #1. Demoted: outcome is predictable from cycles 13/15
   (wins Hyser, ties OTB, small CapgMyo/CEMHSEY regressions) and would not clear the
   "robust across real sets" bar. Low-risk engineering option, not a headline candidate.

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
- **Residual-domain cross-channel subtract / reordering the pipeline to temporal-first**
  (`xres`, retired 2026-08-16): the per-channel LMS is a high-pass that removes the shared
  low-frequency volume-conduction mode carrying the inter-channel MI, so `ρ_e ≪ ρ_x` and the
  spatial stage finds less to take — worse on all 4 real sets at *identical* cost (P7). The
  "score what you code" criterion fix is correct but second-order; stage order dominates it.
- **Lag/delay search on the cross-channel edge** (`xlag`, 2026-08-16, kept only for its
  CapgMyo corner but **spent negative**): the ≤72-option `(parent, delay)` search is a strict
  superset of the incumbent's yet *loses* 6.1 pp of xchan gain on OTB — selection bias over a
  large hypothesis set fitted on 248 samples swamps the alignment gain, and the neighbour
  cross-spectrum is dominated by its zero-phase term anyway (P6). Also the only registered
  codec that fails `neural_ok`. A genuinely different variant must first *shrink or
  better-fund* the estimator, not widen the search.
- **Unconditional (un-gated) Chow–Liu spanning-tree pairing** (`xtree`, kept as the tight-array
  corner but not a general win): optimal structure given *true* MIs, but the backward weights
  are estimated from one 256-sample block over ≈5C edges, so the gain decays +0.96 pp (C=64)
  → +0.39 pp (C=128) → −0.06 pp (C=320) (P8). Re-propose only in *scale-gated* form.

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

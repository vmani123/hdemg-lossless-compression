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
- **Ceiling probe — the non-linear lever, MEASURED (015, 2026-08-03).** An LMCompress-style
  learned front-end (`research/lm_probe.py`: an MLP → discretised-logistic **NLL = the ideal code
  length**, so no arithmetic coder needed) was given the **same causal context** as the champion
  (own past deltas + the concurrent best-neighbour + all channels' lagged delta). The idealised
  nonlinear model **ties `LMS4+xchan_bp` within ±2 % on all four real sets** (Hyser −0.9 %, OTB
  +1.0 %, CEMHSEY −2.0 %, CapgMyo +1.9 %). The paper's "halving" does **not** transfer: after a
  low-order predictor the HD-sEMG residual is near-white sensor noise no model can predict, so
  **nonlinearity is not an accessible lever on the temporal axis** — even a generous (idealised NLL,
  within-recording-trained) model can't beat the linear codec. **One exception, and it is spatial:**
  on CapgMyo (neighbour |corr|≈0.29) the nonlinear model **doubles** the linear best-partner's
  cross-channel gain (+3.8 % vs +1.8 %) → the only redundancy a rank-1 linear subtract misses is
  **nonlinear cross-channel on low-linear-correlation differential arrays.** Even that is ~2 %
  idealised and costs ~190–800× the compute + float `exp`/`sigmoid` + bit-exact determinism ⇒
  `embedded_ok = NO`. **Actionable lead (frontier):** a *cheap integer* nonlinear cross-channel term
  (e.g. a sign/abs cross-product or a small LUT on the best-partner residual), **not** a neural net,
  on differential arrays. Full record: `experiments/015_lm_probe_learned_ceiling.md`.

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

1. **Scale-select the spatial front-end between the two proven per-scale winners**
   (P1b): single *selected* best-partner for `C≤64`, jointly-solved best-*pair* for
   `C≥128`, gated by the decoder-observable channel count (the zero-side-info gate proven
   by `acar_sel`). Both branches and the gate are already verified; this is the first
   construction that could clear the best on the primary Hyser *and* hold the tight-array
   OTB corner. **Highest payoff, lowest mechanism risk.** Risk: the large-array win is only
   +1.12% at higher cost — measure the full 4-set profile before claiming a promotion.
2. **Change the predictor's FUNCTIONAL FORM, not its coefficient count** (P2/P5). A
   linear LMS residual is white *to second order*; any remaining compressibility is
   higher-order. A small sign-of-neighbour or gated-magnitude nonlinearity (still order
   ≤4) is the only live temporal lever. Medium payoff, genuinely different axis, higher risk.
   Pursue only if #1 doesn't clear the best.
3. **Guarantee #1's large-array branch streams** (P4): confirm its per-block pair
   re-selection holds the offline ratio (à la `bestpartner_adaptive`). An embeddability
   guarantee, not a ratio play.

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

## Sanity anchors
- Real embeddable ratios on HD-sEMG live in **~1.3–2.2×**. Any lossless ratio **> ~6×** on
  realistic broadband ⇒ a leak or degenerate data — stop and report.
- **Success is not beating Shannon.** Independent per-channel noise caps lossless at ~3–3.5×.
  Success = beat per-channel FLAC / the embeddable references on real grids at a fraction of
  the compute, proven bit-exact — and, as a stretch, close the gap to offline LZMA.

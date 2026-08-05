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
- **Refinement — on a differential array the residual cross-channel MI is in the VARIANCE, not the
  mean (018).** Diagnosing the learned model's only real edge (CapgMyo): a nonlinear cross-channel
  *predictor* recovers **nothing** (−0.07 bits), but conditioning the coding *scale* on the
  concurrent neighbours' *energy* recovers **+0.318 bits/sample** (vs +0.09–0.11 on the high-corr
  sets). Mechanism = **volume-conduction co-activation** — a motor-unit spike raises energy across
  neighbouring electrodes at once, so on a differential array (low *signed* corr) the cross-channel
  MI hides in the residual **variance**, invisible to a signed rank-1 subtract. Under a REAL causal
  integer Rice-k rule this banks only ~**+0.8 % on CapgMyo** and *hurts* the high-corr arrays (their
  own-EWMA already tracks scale) ⇒ a **geometry-gated scale mechanism** (`+xscale_sel`, like
  `acar_sel`/P1b: ON for low-corr differential arrays only). So CapgMyo is a *smaller* dead end than
  P1 implied — a real ~1 % lever lives there, in the scale. See `experiments/018_*`.
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
- **Ceiling probe — the non-linear lever, MEASURED by TWO model classes (015 + 016, 2026-08-03).**
  An LMCompress-style learned front-end (**NLL = the ideal code length**, so no arithmetic coder
  needed) was given the **same causal context** as the champion (own past deltas + the concurrent
  best-neighbour + all channels' lagged delta) and measured on all four real sets. It **ties
  `LMS4+xchan_bp` within ±2 %** — and this was confirmed by **two independent architectures that
  agree to ~0.7 %**: a tiny order-8 **MLP** (`research/lm_probe.py`, 015) and a **4-layer causal
  Transformer** with 32× the temporal context and ~10× the params (`research/lm_probe_transformer.py`,
  016). Per-set Δ vs champion: Hyser −0.9 %, OTB +1.0 %, CEMHSEY −1.2/−2.0 %, CapgMyo +1.4/+1.9 %.
  The paper's "halving" does **not** transfer, and it is **not** a model-weakness artifact: adding
  attention, depth, and long context buys ~nothing, because after a low-order predictor the HD-sEMG
  residual is near-white sensor noise no model can predict. **Nonlinearity — and long-range temporal
  structure — are not accessible levers on the temporal axis** (strong confirmation of P2); the
  ceiling is **data-limited, not model-limited**. **Confirmed against the ACTUAL paper model (017):**
  the real 110M **bGPT-audio** (LMCompress's audio net, pretrained on LibriSpeech) run zero-shot gets
  only **~1.07× on 16-bit lossless** — worse than `delta+Rice` (16-bit bytes are OOD for an 8-bit
  audio model); in its native 8-bit format (lossy) it beats temporal-only `LMS+Rice` by +14.9 % but
  **still loses to the cross-channel champion** because it is mono. So a *domain-matched* small model
  only ties us and the *actual* (domain-mismatched, mono) paper model is worse: **scale is not the
  missing ingredient — cross-channel structure and embeddability are** (and a domain-matched large
  model is ill-posed here: no HD-sEMG pretraining corpus). **One exception,
  and it is spatial:** on CapgMyo (neighbour |corr|≈0.29) both learned models find a **nonlinear
  cross-channel** gain the rank-1 linear best-partner misses (+1.4/+1.9 % over champion; the MLP
  ~doubles the linear +1.8 % xchan gain). Even that is idealised and non-embeddable (~470 k params +
  attention, float transcendentals, bit-exact-determinism requirement ⇒ `embedded_ok = NO`).
  **Actionable lead (frontier):** a *cheap integer* nonlinear cross-channel term (e.g. a sign/abs
  cross-product or a small LUT on the best-partner residual), **not** a neural net, on differential
  arrays. Full records: `experiments/015_lm_probe_learned_ceiling.md`, `experiments/016_lm_probe_transformer.md`.

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

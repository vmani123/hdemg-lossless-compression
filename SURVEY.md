# SURVEY — lossless multichannel biosignal compression candidates

Forward-looking, cost-filtered watch-list of **lossless** methods for the 128-ch
RHD2164 / HD-EMG node (STM32H745 Cortex-M7 + Spartan-7 XC7S25; integer/fixed only;
causal/streaming; must beat per-channel FLAC by exploiting cross-channel
correlation). **This file PROPOSES only** — no measured ratios, no codec edits.
Watch-list methods are never promoted without explicit human approval.

**Cycle-log note (analysis, 2026-08-10 — results of rows 1–3 below).** All three
slate rows were implemented, measured on 4 real sets, and double-verified
(`results/cycle_bench.csv`; experiments 015–017). **Row 3 (`bias`) WON and is
PROMOTED** — `LMS4bc+Rice+xchan_bestpartner`, +0.213/+0.854/+0.244/+0.739% over the
previous best on hyser/otb/capgmyo/cemhsey, the only candidate since cycle 7 to beat
it on all four; new INSIGHTS **P6**. **Row 1 (`xlag`) is spent NEGATIVE** (−5.75% on
OTB against its own τ=0 reduction; only gain was on CapgMyo, the *predicted negative
control*) → the lag axis is an INSIGHTS **dead end (P1a)**: HD-sEMG cross-channel MI is
carried by instantaneous volume conduction, not the travelling wavefront. **Row 2
(`bprank`) is spent ≈0/negative** — it lands *below both* of its own branches on 3 of 4
real sets (**P1c**: a backward gate whose decision margin is smaller than its
estimator's variance loses to committing to either branch). Neither is retired (each
holds one non-dominated real-data corner), but neither mechanism should be re-proposed.

**Next hypotheses, ranked by expected payoff (consistent with the refreshed INSIGHTS
frontier — proposals only, no measured claims):**

1. **`LMS4bc_adaptive` — the bias corrector on the STREAMING front-end** (P6 × P4).
   The promoted best still uses the *offline* whole-signal `_bp_select` + β, so its
   headline is not an on-node number; the bias stage is already zero-side-info and
   look-ahead 0, and `bestpartner_adaptive` is known to hold the offline ratio within
   ~0.4%. Highest payoff, near-zero mechanism risk: it converts the new best from a
   ratio claim into a portable one. Verdict **embeddable** (both halves already verified).
2. **Re-shape the bias context — widen the spatial axis, shrink the temporal one**
   (P6). The gain concentrated on the sets with the strongest cross-channel structure
   and the informative bit is the *parent-residual sign*, so try (2 parents' signs) or a
   3-level quantised parent residual while dropping `sgn e[t−2]` — at equal or smaller
   table size. This is also the only route to pull cost 0.098 back toward 0.04, which is
   what currently stops the new best from Pareto-dominating its predecessor. Verdict
   **embeddable**. Caveat: keep the context alphabet **structural and always-on** — P1c
   forbids turning it into an estimated per-block selection gate.
3. **Magnitude-bucketed (second-order) bias context** (P6 → P2). If `E[e|sgn ctx]` is
   non-trivial, so may be `E[e | quantised |e[t−1]|]` — still a scalar-mean estimate per
   bucket, still order ≤4, but a genuinely different non-linearity from the sign axis.
   Verdict **borderline** (state cost grows with bucket count); pursue only if #2 saturates.

**Cycle note (survey refresh 2026-08-10, after cycle 15 / `acar_sel`).** Read
against `INSIGHTS.md` P1–P5 + the 9 retired codecs in `research/registry.py`.
Two survey rows are now **closed by measurement** and removed from the live
table: old row 1 (channel-count-gated spatial front-end) is superseded — cycle 13
(`jointbp2`) measured both per-scale branches, so the naive `C`-gate's ceiling is
now *known and bounded*, and it would inherit `jointbp2`'s 320-ch CEMHSEY
regression (see new row 2, which repairs the gate's granularity); old row 4
(NLMS/leaky higher-order LMS) is closed by P2 (order >4 hurts; `LMS4rs` retired).
Three genuinely distinct new mechanisms are proposed below — one **spatial**
(a lag axis no registered codec has ever had), one **model-selection**, one
**temporal-functional-form**.

## Verdict key
- **embeddable** — integer, causal, bounded state/look-ahead, fits the sEMG budget
  (≤1831 cyc/sample-ch) and plausibly the 30 kHz neural budget (125 cyc).
- **borderline** — embeddable only after a specific simplification (noted).
- **watch-list** — expected to fail the cost gate today; track, never auto-promote.

## Live embeddable candidates (ranked, not yet spent)

Ranked by expected payoff. Rows 1–3 are this cycle's slate; rows 4–5 are the
standing value/2D entries carried forward.

| # | method | mechanism (one line) | why it may beat the current best | verdict | key caveat |
|---|---|---|---|---|---|
| 1 | **`xlag` — propagation-aware (time-lagged) cross-channel predictor** | keep the proven **rank-1** best-partner subtract but search **(parent, lag τ∈[−L..+L])** instead of parent-at-τ=0; optionally an MPEG-4-ALS-style 3-tap cross-prediction filter on the selected parent; per-block backward re-selection ⇒ zero side-info | **A spatial MI slice no registered codec can reach.** HD-sEMG MUAPs *propagate* along the fibres at ~3–5 m/s; at 8–10 mm IED that is ~1.6–3.3 ms = **3–7 samples at 2048 Hz**, so the inter-channel cross-correlation peaks at a **non-zero lag** τ\*, which is exactly how MFCV is estimated from a cross-correlogram. Reducible bits for a jointly-Gaussian pair ≈ −½log₂(1−ρ²) is monotone in \|ρ\|, and ρ(τ\*) ≥ ρ(0) by definition of the peak — for a travelling wavefront ρ(0) can be near zero or *negative* when the delay approaches a half-cycle of the 60–120 Hz MUAP band. **Every** spatial construction in the ledger (`xchan`, `bestpartner(_adaptive)`, `multiparent`, `joint2`, `jointbp2`, `iklt(_adaptive)`, `acar`) evaluates the parent at time *t* only, so this redundancy is structurally invisible to all of them | **embeddable** | the parent channel's whole block is already reconstructed before channel *c* (parents idx<c), so **either-sign lags cost no look-ahead beyond the existing Rice block**; per-sample encode unchanged (1 shift-mul-sub), only the per-block selection search grows ×(2L+1), amortised over 512 samples. Predicts CapgMyo stays the negative control (differential montage, 1 kHz, sub-sample delay) — do not read that as failure |
| 2 | **`bprank` — per-channel backward-adaptive spatial model-ORDER gate (rank-1 vs jointly-solved rank-2)** | per channel *and* per block, pick single selected parent (`bestpartner`) vs jointly-solved best pair (`jointbp2`) by comparing the two hypotheses' **measured code cost on the previous reconstructed block** + a small MDL-style complexity penalty and hysteresis; decoder repeats the test ⇒ zero side-info | P1b says selection and count are substitutes **set by geometry** — but geometry is not uniform *within* an array: edge/corner channels have fewer causal parents, channels near an innervation zone or over a second muscle have a rank-1 local mode, interior channels of a diffuse large array are rank≥2. Cycles 12/13 measured the optimum flipping **between arrays**; the same argument says it flips **between channels**. Selecting per channel by empirical code length over the *union* of the two hypothesis classes has expected code length ≤ min of either fixed class, up to an O(log) selection-noise term the block penalty controls. `acar_sel` (cycle 15) already proved a zero-side-info gate is legal and lossless-safe — this puts the gate at the **right granularity** | **embeddable** (both branches + the gate pattern already verified) | **This is the repaired form of INSIGHTS frontier #1, not the naive one.** A global `C`-gate (`C≤64` → best-partner, `C≥128` → joint pair) would send 320-ch CEMHSEY to the rank-2 branch and *inherit* `jointbp2`'s −0.17% there, and its Hyser upside is already bounded by a measured branch. Cost ceiling ≈ `jointbp2`'s; must show it isn't just paying `jointbp2`'s price for `bestpartner`'s answer |
| 3 | **`bias` — context-conditioned integer bias cancellation on the prediction** (frontier #2, nonlinear *functional form*, order ≤4) | after the order-4 sign-sign LMS + xchan subtract, subtract an integer `B[ctx]` learned by a running (sum, count) accumulator, `ctx` = quantised signs of the last two own residuals × sign of the co-located parent residual (~9–27 contexts/ch) | LMS whitens the residual **to second order only** — it zeroes *linear* correlations, not `E[e_t | f(history)]` for nonlinear `f`. P2's saturation is a statement about the *linear* class; any surviving `E[e|ctx] ≠ 0` is first-order-removable structure **no linear predictor of any order can represent**. By the law of total variance, removing it lowers residual variance by exactly `Var(E[e|ctx])` ⇒ shorter Rice codes. Physical source: MUAPs are asymmetric biphasic and firing is bursty, so residual sign-runs carry a non-zero conditional mean; and the *sign-sign* (non-normalised) LMS update itself lags during amplitude transients, leaving a context-dependent DC | **borderline → embeddable** | **Must be distinguished from two retired codecs, and is:** it is NOT `LMS4rs` (retired) — that forked whole *coefficient sets* per activity regime, splitting the adaptation data across predictors (P2's named failure); here the linear predictor stays single and fully adapted, only a scalar additive DC is learned. It is NOT `xctx` (retired) — that conditioned the Rice parameter *k*, a back-end lever P5 declared spent; this changes the **prediction**, i.e. exactly the upstream place P5 says to spend. Highest mechanism risk of the three. Use JPEG-LS's counter-halving so the correction is a shift, never an `SDIV` |
| 4 | **FLAC fixed polynomial predictors (0–3), best-per-block + Rice** | pick-best-per-block fixed polynomial | cheapest upgrade over order-1 delta; near-LMS ratio at a fraction of the compute | **embeddable — shipped** (`fixed0-3+Rice`, on the Pareto front) | the value pick; already registered |
| 5 | **JPEG-LS / LOCO-I 2D over the grid×time image** | MED/LOCO 2D *predictor* over the electrode grid | MED + 2D causal template exploits grid structure a 1-parent subtract approximates | **borderline** | context state per gradient bucket × channel; must beat rows 1–2 on a real 5×13/8×16 grid, not natural images. NB the lever here is the 2D **predictor** only — entropy-context on the Rice parameter is spent (P5) |

### Ranking rationale
Row 1 is ranked first on **ceiling**: it is the only proposal that enlarges the
*amount* of cross-channel MI reachable at all (P1's dominant lever), rather than
re-allocating MI the existing front-ends already see. Row 2 is the **risk-adjusted**
pick — both branches and the gate pattern are already verified, so it is the most
likely of the three to clear the promotion bar, just with a bounded upside; run it
first if the cycle wants the safe win. Row 3 is the only live temporal lever and
should be judged on whether `Var(E[e|ctx])` is non-trivial after LMS at all.

## Watch-list — DO NOT promote without human approval

Methods that fail the integer / causal / streaming / lossless gates today; tracked
for offline baselines and future reference only.

| method | note |
|---|---|
| Integer discrete flows (IDF), L3C, learned entropy models | learned lossless; float/GPU, no streaming budget — offline baselines only |
| Convolutional autoencoder + lossless residual | float core; disqualified on the FPGA target |
| VAE-DCT / neural context models | fail integer + latency gates today |
| TSCom-Bench / chained lightweight neural predictors (arXiv 2509.21002) | learned-lossless time-series; float/GPU, no streaming budget |
| GPU adaptive lossless FP framework (arXiv 2511.04140) | offline/GPU float pipeline; no integer streaming budget |
| Predictability-aware multichannel TS (arXiv 2506.00614) | lossy + neural + non-causal; disqualified, tracked for record |
| Compressive on-chip AP recording (IEEE TBME 11183845) | **LOSSY** (requantise + MI selective sampling); disqualified by lossless-only, listed for record |
| **HD-sEMG-CORE** (IEEE 10785553, 2024/25) — GAN+VAE compression with U-Net latent restoration | **LOSSY** (scored by MSE/PSNR/SSIM, not bit-exactness) and float/GPU — disqualified twice over. Listed because it is the closest-named HD-sEMG-specific compression work; useful only as evidence of the data-volume problem, never as a bar |

**Reference-only (not contenders):** streaming floating-point time-series
compressors (Elf / Chimp / Gorilla, arXiv 2510.07015) are XOR-of-float oriented —
a poor fit for int16 biosignals where Rice/Golomb already dominates. Multichannel
biomedical sequential compression (arXiv 1605.04418) and 2D lossless EEG coding
are the closest published framings of our problem; both confirm the
predict-then-entropy-code shape we already use.

## Literature grounding for row 1 (the ALS precedent)
MPEG-4 ALS's **multichannel coding (MCC)** tool does not subtract a reference
channel at zero lag: it applies a **3-tap cross-prediction filter** to a *selected*
reference channel's residual, plus a **time shift**, precisely because inter-channel
redundancy in an array arrives *delayed*. The same architecture has been applied to
multichannel **ECG** and other biomedical signals (paper-reported, unverified here).
Our `bestpartner` family has the "selected reference channel" half of that design
and is **missing the time-shift half** — row 1 supplies it, with the delay predicted
a priori by muscle-fibre conduction velocity rather than searched blindly.
Sources: [MPEG-4 ALS standard overview](http://elvera.nue.tu-berlin.de/typo3/files/1216Liebchen2009.pdf) ·
[MPEG-4 ALS inter-channel prediction for multi-channel ECG](https://ieeexplore.ieee.org/document/4458176/) ·
[MFCV from electrode arrays / cross-correlogram peak delay](https://link.springer.com/article/10.1007/BF02441587) ·
[LOCO-I/JPEG-LS bias cancellation (row 3)](https://ieeexplore.ieee.org/document/855427) ·
[HD-sEMG-CORE (watch-list)](https://ieeexplore.ieee.org/document/10785553/)

## The settled facts (from INSIGHTS, so the survey doesn't re-propose them)
- Cross-channel decorrelation is the dominant lever, but it is a **single rank-1
  adaptive subtract** — multi-tap *spatial* transforms (fixed or adaptive) and
  *summed* multi-parent subtracts are dead ends (P3, P1b). Row 1 stays rank-1 in
  space; its extra taps are **temporal on one parent**, which P3 does not cover.
- The entropy back-end is at the floor — Rice is optimal for the near-geometric
  residual; neither an ANS swap nor any context-model of the Rice parameter helps (P5).
- Deeper/branched **linear** temporal prediction is spent (P2): order >4 hurts and a
  coefficient-set bank (`LMS4rs`) is retired. Only a change of *functional form*
  (row 3) is live.
- A geometry-dependent lever must be **gated on something the decoder can observe**
  (`acar_sel`); row 2 extends that from a header constant to a per-channel backward
  measurement.

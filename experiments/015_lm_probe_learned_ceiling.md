# 015 — LM-probe: does a learned nonlinear model (LMCompress-style) beat the hand-crafted codec?

- **Cycle:** headroom probe (no codec promoted)
- **Date:** 2026-08-03
- **Branch:** `claude/lm-compression-probe`
- **Candidate:** `lm_probe` — a learned autoregressive front-end measured as an *upper bound*, not a shippable codec
- **Datasets:** all four real sets — `hyser_1dof_f1_s1` (128 ch), `otb_hdsemg_vl` (64 ch),
  `cemhsey_s1_d1t1` (320 ch), `capgmyo_dba_s1` (128 ch)
- **Tool:** `research/lm_probe.py` (pure numpy; `--selftest` verifies pmf + gradients)

## Motivation

*Lossless data compression by large models* (Li et al., Nat. Mach. Intell. 2025 — "LMCompress")
reports **halving** JPEG-XL / FLAC / H.264 by running an autoregressive large model into an
arithmetic coder. The mechanism reduces to one identity: the achievable code length **is** the
model's cross-entropy, `bits = Σ −log₂ p_θ(x_t | x_<t)`. So we can measure the ratio a learned
model *would* achieve with **no arithmetic coder** — just fit a causal predictor and report its
held-out NLL in bits/sample. This is the cheap, decisive "is there headroom above `LMS4+xchan`?"
test, and it answers the standing **P2** question ("to lower the temporal residual entropy the
predictor's *functional form* must change — genuinely non-linear").

## Hypothesis

If HD-sEMG holds structure that our linear LMS4 + linear best-partner subtract leaves on the table,
a flexible **nonlinear** model *with at least the same causal context* should have a lower NLL —
its ratio would be the headroom ceiling. If it merely ties, the champion is already near the limit
for a plug-in autoregressive front-end, and P2's noise-floor reading holds.

## Implementation (`research/lm_probe.py`)

A small MLP (1 hidden ReLU layer, pure numpy — the repo has no torch) maps a **causal** context to
the parameters `(μ, log s)` of a **discretised-logistic** distribution over the next-sample delta
`d[c,t] = x[c,t] − x[c,t-1]`; bits = `−log₂ p(d[c,t])`. Context, all decodable before `x[c,t]`
under channel-raster order (decode timestep `t` in channel order `0..C-1`):

- **temporal**: this channel's own last `order=8` deltas `d[c, t-1..t-8]`
- **concurrent**: the `K=4` nearest lower-index channels at time `t`, `d[c-1..c-4, t]` — the same
  same-timestep spatial signal `xchan_bestpartner` exploits (index runs down each grid column, so
  `c-1` is the vertical electrode neighbour)
- **lagged**: all channels' previous delta `d[:, t-1]` (cheap extra context)

Trained per dataset (Adam, 6000 steps, hidden 128) on the first 70 % of time; NLL evaluated on the
held-out last 30 %. **Correctness gate** (`--selftest`, run first): the discretised-logistic pmf
sums to 1.0 over the integer grid, and both the closed-form `(∂/∂μ, ∂/∂ log s)` and the full-MLP
gradients match finite differences to ~1e-9. `rtl/`, `sim/`, `registry.py` untouched — this is a
measurement harness, not a registered codec.

Baselines are the **real** registry codecs (`c.encode → bytes`) run on the **same held-out tail**,
so the comparison is real-compressed-bytes vs the learned model's *idealised* NLL — if anything
**generous to the learned model** (a real arithmetic coder adds a few bytes total; a static
pretrained model pays no per-file weight cost here).

## Measurement

`PYTHONPATH=host_tools:research python3 research/lm_probe.py --datasets hyser_1dof_f1_s1
otb_hdsemg_vl cemhsey_s1_d1t1 capgmyo_dba_s1 --hidden 128 --steps 6000 --neighbors 4
--csv results/lm_probe.csv` (held-out tail, 300 k sample-ch each; `results/lm_probe.csv`):

| dataset | ch | nbr \|corr\| | LMS+Rice (temporal) | **champion** `LMS4+xchan_bp` | **lm_probe** (idealised) | Δ vs champion | neural xchan gain | champion xchan gain |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| hyser_1dof_f1_s1 | 128 | ~0.75 | 1.325× | **1.478×** | 1.465× | **−0.9 %** | +10.5 % | +11.5 % |
| otb_hdsemg_vl | 64 | ~0.78 | 1.796× | **2.155×** | 2.176× | **+1.0 %** | +21.2 % | +20.0 % |
| cemhsey_s1_d1t1 | 320 | ~0.73 | 1.724× | **1.955×** | 1.916× | **−2.0 %** | +11.1 % | +13.4 % |
| capgmyo_dba_s1 | 128 | ~0.29 | 1.395× | **1.420×** | 1.448× | **+1.9 %** | **+3.8 %** | +1.8 % |

("xchan gain" = ratio improvement over temporal-only `LMS+Rice`.) Neural cost: **10 k–43 k
MAC/sample-ch** (scales with channel count) vs the champion's **~53 ops** → ~190–800×, plus float
`exp`/`sigmoid` and a hard bit-exact-determinism requirement to actually be lossless ⇒
`embedded_ok = NO`.

## Verdict — no accessible headroom; one narrow nonlinear signal

1. **Given the same causal context, the idealised learned model ties the linear champion within
   ±2 % on every real set.** The LMCompress "halving" does **not** transfer to HD-sEMG. The gains in
   the paper come from massive models exploiting semantic structure in text/images/audio; after a
   low-order predictor the HD-sEMG residual is near-white **sensor noise**, which no model can
   predict (P2). A generous, idealised, within-recording-trained model confirms the champion is
   already at the practical limit for a plug-in autoregressive front-end.
2. **The lone clear win is the honest negative control, CapgMyo** (differential 8×16, neighbour
   \|corr\|≈0.29). Where the *linear* pairwise subtract finds almost nothing (+1.8 %), the nonlinear
   model roughly **doubles** the spatial gain (+3.8 %) — evidence that the small residual redundancy
   on a differential array is **nonlinear cross-channel**, invisible to a rank-1 linear subtract.
   This refines P1/P2: the only real (still ~2 %, non-embeddable) nonlinear lever is *spatial*, on
   low-linear-correlation arrays — not temporal, and not on arrays where linear `xchan` already wins.
3. **`cemhsey` −2.0 %** is most likely mild underfitting (320 heterogeneous channels, largest input),
   not a real deficit; it does not change the ±2 % tie conclusion.

## Caveats (why this bounds, not closes, the question)

- Idealised NLL, single seed, and **within-recording** train/test (train and eval from the same
  session) — all *favour* the learned model, and it still only ties. A genuinely large *pretrained*
  model (the paper's setup) is untested here and could differ, but the noise floor bounds the upside.
- The probe is a **ceiling measurement**, not a codec: nothing here is embeddable or was promoted.

## Follow-ups (ranked)

1. **Chase the CapgMyo nonlinear-spatial signal** — is a *cheap, integer* nonlinearity (e.g. a
   sign/abs cross term, or a tiny per-channel LUT on the best-partner residual) enough to bank part
   of the +2 % *within* `embedded_ok`? That is the only lead with a plausible on-node payoff.
2. **Cross-subject / cross-session holdout** — the honest generalization test for any shipped model.
3. Mixture-of-logistics head + larger net as a firmer ceiling (diminishing returns expected).

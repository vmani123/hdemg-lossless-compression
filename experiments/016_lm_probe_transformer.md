# 016 — On-domain Transformer probe: is the 015 ceiling a model-weakness artifact?

- **Cycle:** headroom probe (confirmation of 015; no codec promoted)
- **Date:** 2026-08-03
- **Branch:** `claude/lm-compression-probe`
- **Candidate:** `lm_probe_transformer` — a causal Transformer, measured as an upper bound (ideal NLL)
- **Datasets:** all four real sets
- **Tool:** `research/lm_probe_transformer.py` (torch, CPU; `--selftest` checks pmf + forward/backward)

## Motivation

015 showed a small **MLP** (order-8 temporal + concurrent neighbour + lagged all-channel context)
ties the linear champion within ±2 %. Fair objection: *the MLP is too weak* — the paper's whole
thesis is that a bigger, deeper, longer-context model ("understanding") compresses better, and the
paper's audio model is a **110M-param Transformer** (bGPT-audio) with an ~8 KB attention window.
So an MLP tying the champion may just mean the MLP is underpowered, not that the ceiling is real.

This experiment removes that objection *within our regime* by swapping the MLP for a real
autoregressive **Transformer** — the paper's model **class** — trained on-domain. (It is still not
the paper's *scale*: 110M pretrained on 1000 h of audio. That is untestable here — there is no large
HD-sEMG pretraining corpus, and the paper's own headline is that **domain match dominates**, so a
speech-pretrained model is the wrong tool. On-domain is the fair probe for us; see Caveats.)

## Implementation (`research/lm_probe_transformer.py`)

nanoGPT-style causal Transformer over each channel's delta stream: `d_model=64`, **4 layers**,
4 heads, **context length 256** (32× the MLP's order-8 window — the point is to test long-range
temporal attention), pre-LN blocks, GELU. Same **discretised-logistic NLL head** as 015 (bits =
`−log₂ p`). Cross-channel context kept identical in spirit: the head sees the Transformer state
(own past, via attention) **plus** the K=4 concurrent lower-index neighbours at the target step
**plus** a learned projection of all channels' previous delta — so it has *at least* the MLP's
information. ~470 k params (≈10× the MLP). Inputs standardised by the delta-scale and the head
outputs de-normalised by it (so the head emits O(1) values — without this the model stalls at a
degenerate ~19 bit solution; fixed and verified before the reported run). Trained 3000 steps
(AdamW, lr 1e-3) on the first 70 % of time; NLL on the held-out last 30 % (336 k sample-ch,
warmup 32 skipped). Train curves **flat by ~step 500** → converged, not under-trained. `--selftest`
confirms the pmf normalises and gradients flow. `rtl/`, `sim/`, `registry.py` untouched.

## Measurement

`PYTHONPATH=host_tools:research python3 research/lm_probe_transformer.py --datasets hyser_1dof_f1_s1
otb_hdsemg_vl cemhsey_s1_d1t1 capgmyo_dba_s1 --steps 3000 --eval-windows 1500 --lr 1e-3
--csv results/lm_probe_transformer.csv`:

| dataset | ch | **champion** `LMS4+xchan_bp` | **015 MLP** | **016 Transformer** | Txn Δ vs champion | MLP≈Txn agreement |
|---|--:|--:|--:|--:|--:|--:|
| hyser_1dof_f1_s1 | 128 | **1.478×** | 1.465× | 1.465× | **−0.9 %** | 10.924 vs 10.922 bpp |
| otb_hdsemg_vl | 64 | **2.155×** | 2.176× | 2.176× | **+1.0 %** | 7.353 vs 7.353 bpp |
| cemhsey_s1_d1t1 | 320 | **1.955×** | 1.916× | 1.932× | **−1.2 %** | 8.352 vs 8.282 bpp |
| capgmyo_dba_s1 | 128 | **1.420×** | 1.448× | 1.441× | **+1.4 %** | 11.050 vs 11.107 bpp |

## Verdict — the ceiling is model-agnostic

1. **Two independent architectures converge to the same number.** A tiny order-8 MLP and a 4-layer
   Transformer with 32× the temporal context and ~10× the parameters land within **~0.7 % of each
   other** on every real set, and both sit within ±1.4 % of the linear champion. The 015 tie was
   **not** an MLP-weakness artifact.
2. **Long-range temporal attention buys ~nothing** (Transformer ≈ MLP on the temporal-dominated
   sets) — a direct, strong confirmation of **P2**: after a low-order predictor the HD-sEMG residual
   is near-white sensor noise, so neither depth, attention, nor 256-sample context finds structure a
   linear order-4 predictor misses. The paper's "understanding → compression" gains need learnable
   semantic structure that noise-dominated HD-sEMG does not have.
3. **The one consistent positive is again CapgMyo** (+1.4 % Txn, +1.9 % MLP) — the low-linear-
   correlation differential array. Both model classes independently find a small **nonlinear
   cross-channel** gain the rank-1 linear best-partner leaves behind. This is the only lead with a
   mechanism (P1/P2 refinement in `INSIGHTS.md`).
4. Still non-embeddable (~470 k params + attention ⇒ `embedded_ok = NO`).

## Caveats

- **Not the paper's scale.** 110M pretrained on a huge domain corpus is untested (and largely
  ill-posed here: no HD-sEMG pretraining corpus exists; 4 short recordings can't fine-tune 110M).
  But the MLP↔Transformer convergence makes the ceiling look **data-limited, not model-limited** —
  so scaling up is very unlikely to move it, and would face domain mismatch besides.
- Idealised NLL (vs the baselines' real bytes), single seed, within-recording holdout — all *favour*
  the learned model, and it still only ties.

## Follow-up

Unchanged and sharpened from 015: the **only** lead worth on-node effort is a **cheap integer
nonlinear cross-channel term** on differential arrays (CapgMyo-like), targeting the ~1–2 % both
learned models find there — implemented as a codec primitive under `embedded_ok`, not a neural net.

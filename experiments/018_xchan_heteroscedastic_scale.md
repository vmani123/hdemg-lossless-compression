# 018 — Using the paper's METHOD to design our own EMG primitive: cross-channel scale

- **Cycle:** design + proof-of-concept (candidate primitive, not yet registered)
- **Date:** 2026-08-03
- **Branch:** `claude/lm-compression-probe`
- **Tools:** `research/xchan_structure_probe.py` (diagnostic), `research/xscale_poc.py` (real-Rice PoC)

## The question

Given 015-017 (directly porting LMCompress fails), **can the paper's *takeaways* build an
EMG-specific model of our own?** The transferable method is: (1) *compression = prediction* —
score any model by residual code length, cheaply; (2) *understanding = compression* means **match
the model to the data's real structure** (the paper won with domain-specific models, not one generic
net). All three probes agreed the only unclaimed structure is **nonlinear cross-channel**. So use
the neural probe as an *oracle* to design the cheap, embeddable version (distillation, not deployment).

## Step 1 — diagnose WHERE the cross-channel gain lives (`xchan_structure_probe.py`)

Decompose the gain over linear best-partner into a better **prediction** (nonlinear function of
neighbours → smaller residual) vs a better **scale** (residual variance heteroscedastic in neighbour
energy → context-dependent Rice-k). Order-0 entropy (bits/sample), fit on 70 % / measured on 30 %:

| dataset | H(δ) | +linear xchan | **(A) nonlinear predictor** | **(B) neighbour-energy scale** |
|---|--:|--:|--:|--:|
| **capgmyo** (|corr|≈0.29) | 12.054 | 12.007 | **−0.070** | **+0.318** |
| hyser | 11.938 | 11.113 | −0.001 | +0.090 |
| otb | 8.647 | 7.885 | +0.005 | +0.085 |
| cemhsey | 7.240 | 8.628 | +0.060 | +0.113 |

**A nonlinear cross-channel *predictor* is dead (~0, −0.07 on CapgMyo). The lever is heteroscedastic
*scale*:** +0.318 bits/sample on CapgMyo, +0.09–0.11 elsewhere. Physical meaning = **volume
conduction / co-activation**: a motor-unit spike raises *energy* across neighbouring electrodes
simultaneously, even where the *signed* correlation is low — which is exactly why CapgMyo (the
differential low-corr array) shows 3× the gain, and why both a rank-1 linear subtract and a mono
audio model (bGPT, 017) miss it.

## Step 2 — does it survive a REAL integer codec? (`xscale_poc.py`)

Real Golomb-Rice code lengths (bijective ⇒ lossless), k causal & integer, on the linear-xchan
residual. `xscale`: nudge k from the pooled concurrent energy of the 4 nearest lower-index
neighbours vs its EWMA (smooth, λ = modulation strength). Baseline = own-EWMA Rice-k only.

| dataset | baseline b/s | xscale (λ=0.5) | gain |
|---|--:|--:|--:|
| **capgmyo** | 12.112 | 12.012 | **+0.83 %** |
| hyser | 11.179 | 11.207 | −0.25 % |
| otb | 7.946 | 7.996 | −0.63 % |
| cemhsey | 8.686 | 8.751 | −0.75 % |

(Stronger λ helps CapgMyo no further and wrecks the rest: at λ=1.0 the high-corr arrays lose 3–5 %.)

## Verdict — the method works; the prize is real, small, and must be GATED

1. **The design method delivered.** Compression-is-prediction + match-to-structure took us from
   "big models don't port" to a *specific, novel-for-this-repo, mechanistically-grounded* lever:
   **cross-channel heteroscedastic scale** (co-activation), which nothing in the codec zoo exploits.
2. **But the embeddable payoff is modest.** The oracle's +0.318 bits (+2.7 %) on CapgMyo shrinks to
   **~+0.8 %** under a real causal Rice-k rule — Rice can't reach the per-bin-entropy oracle, and the
   own-EWMA already tracks most local scale. On high-correlation arrays it **hurts** (the linear
   xchan already removed the shared component; extra cross-channel scale modulation is just noise).
3. **So `xscale` must be scale-SELECTED, exactly like `acar_sel` (P1b).** Gate it ON only for
   low-linear-correlation differential arrays (decoder-observable via the fitted β magnitudes /
   neighbour corr), OFF elsewhere. Gated, it is a real **+~0.8 % on CapgMyo-class arrays, 0 elsewhere**
   — a legitimate Pareto candidate (near-zero added cost: one compare + add per sample-ch), not a
   breakthrough.

## Follow-up

Register `LMS4+Rice+xchan_bestpartner+xscale_sel` in `registry.py` (gate on β/neighbour-corr) and
bench it bit-exact under `embedded_ok` — the honest expected result is a CapgMyo-only ~+0.8 %,
retired-or-kept on the Pareto rule. The larger lesson for INSIGHTS: **EMG's exploitable cross-channel
redundancy on differential arrays is co-activation *variance*, not signed correlation** — a scale
mechanism, not a predictor.

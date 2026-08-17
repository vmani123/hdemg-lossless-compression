# 017 — LMS4bc+Rice+xchan_bestpartner: context-conditioned integer bias cancellation on the prediction

- **Cycle:** 13
- **Date:** 2026-08-10
- **Branch:** `compression-cycle-2026-08-10`
- **Candidate:** `LMS4bc+Rice+xchan_bestpartner` (a.k.a. `biasbp`)
- **Primary real dataset:** `hyser_1dof_f1_s1` (128 ch, 8×16, 2048 Hz, REAL); also otb / capgmyo / cemhsey
- **Result: PROMOTED — new best embeddable on all four real sets.**

## Hypothesis (SURVEY row 3 = INSIGHTS frontier #2 — change the predictor's FUNCTIONAL FORM)

P2 says temporal prediction saturates and deeper order hurts — but that is a statement about the **linear**
class. An LMS predictor zeroes *linear* correlation only; it does not zero `E[e_t | f(history)]` for
non-linear `f`. Any surviving `E[e | ctx] ≠ 0` is first-order-removable structure that **no linear predictor
of any order can represent**, and by the law of total variance removing it lowers residual variance by
exactly `Var(E[e|ctx])` ⇒ shorter Rice codes. Physical sources: MUAPs are asymmetric biphasic and firing is
bursty, so residual sign-runs carry a non-zero conditional mean; and the *sign-sign* (non-normalised) LMS
update lags during amplitude transients, leaving a context-dependent DC.

## Implementation

`research/registry.py` only (`biasbp_encode`/`biasbp_decode`). The best-partner front-end (`_bp_select`/
`_bp_inverse`) and the order-4 sign-sign LMS are reused **verbatim**, so the only delta versus the incumbent
`LMS4+Rice+xchan_bestpartner` is a JPEG-LS/LOCO-I bias-cancellation stage **between the predictor and the
Rice coder**. `ctx = (sgn e[g,t−1], sgn e[g,t−2], sgn e[parent(g),t])` → 27 contexts/channel (9 live where
best-partner chose no parent); `parent(g) < g` by construction, so the parent's same-slice residual is
decoded before the child's — causal, streaming-legal, zero side-info. Correction tracked divisionless exactly
as JPEG-LS: `B += d; N += 1`, both halved by arithmetic shift at `N = 64`, `C` nudged ±1 when the running sum
leaves `(−N, 0]`, clamped to int8. Encoder and decoder call the identical `_bias_update(st, q, d)` on the
coded residual, so they are a matched pair; no float, divide or multiply in the stage. Integer/fixed only;
`rtl/`, `sim/` untouched.

## Measurement

Command:
`PYTHONPATH=host_tools ./.venv/bin/python research/bench.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl capgmyo_dba_s1 cemhsey_s1_d1t1 synth_sc0.6 synth_sc0.9 --max-samples 15000 --csv results/cycle_bench.csv`

Real data, from `results/cycle_bench.csv` (all `ok=True`, `embedded=OK`, `neural=OK`), cost **0.0983**:

| dataset | C | `LMS4bc` | best `LMS4+Rice+xchan_bestpartner` (0.0394) | **vs best** | best offline ref |
|---|---:|---:|---:|---:|---:|
| **hyser_1dof_f1_s1** | 128 | **1.483533** | 1.480384 | **+0.213%** | lzma 1.6674 |
| otb_hdsemg_vl | 64 | **2.180401** | 2.161938 | **+0.854%** | lzma 1.5826 (beaten) |
| capgmyo_dba_s1 | 128 | **1.353778** | 1.350480 | **+0.244%** | wavpack 1.3472 (beaten) |
| cemhsey_s1_d1t1 | 320 | **1.969994** | 1.955547 | **+0.739%** | lzma 2.0589 |
| *4-set mean* | | | | **+0.512%** | |

**Beats the incumbent best on every real set** — the only candidate in cycles 10–13 to do so. It is also the
strict max-ratio embeddable codec on **otb (2.1804×, > `acar_sel` 2.1795×)** and **cemhsey (1.9700×, >
`bestpartner` 1.9555×)**. On the primary Hyser it is 3rd (behind the non-promoted corners `jointbp2` 1.4969×
and `bprank` 1.4952×, both of which regress OTB/CEMHSEY).

Synthetic (mechanism only): synth_sc0.6 2.617314, synth_sc0.9 2.591866 — 4th of 20 on both, above every
`bestpartner` variant.

## Attribution

**Unambiguous, and it is the temporal/prediction stage — not the front-end and not the back-end.** The
cross-channel front-end (`_bp_select`, offline best-partner + β) and the entropy coder (adaptive Rice) are
bit-identical to the incumbent's; the LMS pass is the same order-4 sign-sign filter. Therefore the entire
+0.213…+0.854% is `Var(E[e|ctx])` being removed by the 27-context integer DC corrector — i.e. **P2's
saturation was a property of the linear class only, and the non-linear functional-form lever is real**.

The gain's *shape* is informative and points at the mechanism: it is largest on **OTB (+0.854%)** and
**CEMHSEY (+0.739%)**, the two sets with the strongest cross-channel structure (achieved xchan gain +18.4%
and +13.1%), and smallest on Hyser (+0.213%) and CapgMyo (+0.244%). The third context bit is the **sign of
the co-located parent residual**, so the corrector is harvesting *residual cross-channel* information that
the rank-1 subtract structurally cannot reach: β is a single scalar per channel-block, hence a
**symmetric** linear map, while `E[e_c | sgn e_parent]` is an **asymmetric, sign-dependent** offset. The
biphasic MUAP shape makes that asymmetry real. In compression terms the corrector removes conditional-mean
structure that survives *both* the linear temporal filter and the linear spatial subtract — a strictly
different slice of `H(e)` from anything spent so far.

Note this is the exact opposite outcome to the two retired lookalikes, and for a reason that generalises:
`LMS4rs` forked whole *coefficient sets* per regime (splitting the adaptation data across 4-tap filters, so
each estimate got noisier — P2's named failure), and `xctx` conditioned the Rice *parameter* (the back-end
lever P5 declared spent, leaving the residual untouched). Here a **scalar mean per context** is estimated —
orders of magnitude fewer samples needed than a 4-tap filter — and it is applied **upstream**, to the
residual stream itself, which is precisely where P5 says to spend.

## Cross-channel gain, isolated (REAL)

Front-end unchanged, so the codec's cross-channel lever is the incumbent's. Achieved gain vs temporal-only
`LMS+Rice` (1.3300 / 1.8254 / 1.3323 / 1.7293): **+11.54% (hyser) / +19.45% (otb) / +1.62% (capgmyo) /
+13.92% (cemhsey)** — the highest achieved cross-channel gain of any registered codec on otb and cemhsey
(incumbent: +11.31 / +18.44 / +1.37 / +13.08%). The increment over the incumbent is the bias stage
*amplifying* the front-end's harvest via the parent-sign context, not a new front-end. Achieved, not a
ceiling.

## Pareto check

Cost **0.0983** vs the incumbent's 0.0394 — 2.5×, dominated by the 27-context table's SRAM (141 B/ch =
18.0 KB at 128 ch), not by compute (+8 ops/sample-ch). So it does **not** Pareto-dominate the incumbent:
higher ratio **and** higher cost. Both stay on the front. The incumbent (and `bestpartner_adaptive`,
`lms4s7+x6/b512`, `delta+Rice+xchan`) remain the value corners; `LMS4bc` is the new **max-ratio** corner and
the new leaderboard best. Nothing dominates `LMS4bc` (it is the strict maximum on two real sets).

## Sanity gates

- Max real ratio **2.1804×** (otb) ≪ the 6× ceiling → honest broadband EMG, no leak.
- 120/120 bench rows `ok=True` — no FAIL bit-exact.
- **No regression anywhere:** ≥ incumbent on all four real sets and both synthetics.
- `embedded_ok` OK; `neural_ok` OK (45 enc ops/sample-ch).
- Extra verification beyond the gate (bit-exact): shapes 1×50, 2×3, 8×1, 16×777, 64×300, 5×1000 random; a
  bursty MUAP-like 32×2000; an all −32768 saturation case; all-zeros. Stage confirmed live, not a no-op:
  85.8% of samples receive a non-zero correction on the bursty synthetic, max |C| applied = 13.

## Verification

**Verifier A — PROMOTE. Verifier B — PROMOTE.** Unanimous, no split.

## Decision

**PROMOTED — new leaderboard best embeddable.** It beats the current best on **all four** real sets
(+0.213…+0.854%, mean +0.512%) and had a unanimous PROMOTE, satisfying both halves of the promotion rule. The
port headline's max-ratio slot moves to `LMS4bc+Rice+xchan_bestpartner`; the minimal-hardware slot
(`lms4s7+x6/b512`) is unchanged, and `LMS4+Rice+xchan_bestpartner` is **not** retired (cheaper, non-dominated).

**Port caveat carried over unchanged (P4):** `LMS4bc` sits on the **offline whole-signal** `_bp_select`
front-end and transmits `(parent, β)` per channel as side-info, exactly like the incumbent — so the headline
ratio is not an on-node encoder's. **The bias stage itself is pure streaming, zero side-info, look-ahead 0**;
the missing measurement is the bias stage stacked on `bestpartner_adaptive`. That is now the top open item.

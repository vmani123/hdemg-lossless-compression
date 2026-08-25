# SOTA review & headroom analysis — 2026-08-25

Full-project review: where 36 research cycles landed, how the embedded codecs
compare to the state of the art in nervous-system data compression, an audit of
the `embedded_ok` gate, and a measured answer to "how much progress is left."

**Provenance.** Every repo number below comes from `results/*.csv`,
`research/CYCLE_LOG.md` rows 1–36, or fresh measurements run on the cached
corpus (`sim_data/corpus_npz/`, first 15 000 samples, matching the bench).
Every literature number was pulled by a survey pass and then adversarially
re-verified against the primary source (paper/PDF/repo); corrections found in
verification are already applied here. Nothing in this file is from memory or
reasoning alone.

---

## 1. Verdict up front

1. **The within-family plateau is real and measured.** All 36 cycles combined
   moved the best 4-set real mean by **+1.02%** (1.73021× → 1.74788×); the
   cross-channel step contributed **71.6% of all gain ever recorded** (in log
   terms) before cycle 1. Rate of return decayed monotonically
   0.057 → 0.032 → 0.021 → 0.018 → **0.000 %/cycle** (last 3 cycles: exactly
   zero movement of the best mean). 2 promotions in 36 cycles, none in the
   last 9 rows. 9 of 13 principles plus 2 sub-axes are formally closed; the
   entire remaining frontier consists of gates between already-measured
   branches, whose ceiling a perfect 4-way per-dataset oracle bounds at
   **+0.51%** (corner mean 1.75679 vs tip 1.74788).
2. **Against published SOTA, the project is at or beyond the frontier for its
   signal class** (§3). The apparent 3–3.6× results on neural/EEG/ECG data
   dissolve under honest normalization (bit depth, container padding,
   oversampling). Nothing published beats ~1.75× mean on comparable-entropy
   16-bit surface biosignals, and the mechanism set here (causal
   reference-channel prediction + context bias correction + adaptive Rice) is
   the same one the best published multichannel coders converged on —
   Capurro et al. 2017 explicitly measured that it beats full multivariate RLS.
3. **The biggest apparent gap in the repo — offline LZMA +12.3% on Hyser,
   +4.4% on CEMHSEY — is now largely explained, and it is not a codec
   weakness: it is a corpus quantization artifact** (§4). Hyser samples sit on
   a ~50-count value lattice (~460 distinct values/channel), CEMHSEY on a
   ~8-count lattice; the pipeline's `>>8` fixed-point arithmetic destroys that
   structure before coding, while byte-oriented LZMA partially exploits it. A
   symbol-aware coder on plain time-delta would reach ~2.14–2.26× on those two
   sets. **This is the same phenomenon as Buccino 2023's "LSB correction" on
   Neuropixels and the Neuralink challenge's non-uniform 10-in-16-bit upscale
   (brainwire brute-forced the dequantization map).** The RHD2164's native ADC
   stream will not have this lattice — so the right response is to normalize
   the corpus (map to true digital codes), not to ship a lattice-exploiting
   codec.
4. **`embedded_ok` should be fleshed out, and the audit found one outright bug**
   (§5): the "backward-adaptive family streams" check in `embedded_verify.py`
   is vacuous (it compares `encode(A)==encode(A)` on identical prefixes), the
   gate remains 100% self-reported (it has never rejected a registered codec),
   `--strict` is wired into no hook or CI, 15 registered codecs (including the
   headline) fail it today under a prose-only waiver, and the declared
   `_BP_SELECT_OPS = 8` is ~an order of magnitude below the real work — which
   means **`neural_ok` for the whole bestpartner family is decided by
   declaration and would likely flip under measurement.**
5. **Realistic remaining headroom** (§4, measured): on honest (lattice-free)
   data, ~**+2–5% mean** from context-conditioned entropy coding (measured
   conditional structure of 0.06–0.42 bits/sample survives even perfect
   non-causal linear prediction; largest on CapgMyo) plus possibly a few
   percent from a group reversible integer transform on the high-correlation
   sets. On the bench as currently constituted, up to **+20–25 pp of mean
   ratio** — but ~85% of that is the corpus lattice, i.e. benchmark inflation,
   not deployable value. The physics ceiling is also tighter than assumed: the
   RHD2164's own 2.4 µVrms input-referred noise (≈12.3 LSB at 0.195 µV/LSB)
   caps lossless at ≈**2.8×** on quiescent 16-bit channels, before
   electrode-skin noise (Huigen 2002: 1–20 µVrms) — the stated 3–3.5× cap is
   optimistic for this front-end.

---

## 2. Trajectory: what 36 cycles actually bought

| era | codec | Hyser | 4-set mean | Δmean |
|---|---|---:|---:|---:|
| baseline | `delta+Rice` | 1.3090 | 1.50472 | — |
| temporal | `LMS+Rice` | 1.3300 | 1.55423 | +3.29% |
| **cross-channel** (pre-cycle) | `LMS+Rice+xchan` | 1.4738 | 1.73021 | **+11.32%** |
| promotion 1 (cycle 7) | `LMS4+…+bestpartner` | 1.4804 | 1.73709 | +0.40% |
| promotion 2 (cycle 27) | `LMS4bc+…` | 1.4851 | 1.74673 | +0.55% cum. |
| mean tip (cycle 32) | `LMS4bcxs+…` (not promoted) | 1.4849 | **1.74788** | +0.07% |
| cycles 34–36 | headline unchanged | 1.4851 | 1.74788 | **+0.000%** |

Rate of return per cycle: 0.043%/cycle (cycles 1–15) → 0.005%/cycle (last 10)
— a ~9× collapse. ~20 of ~36 candidate slots went to axes that returned zero
or negative (lag search ×5, rank gating ×3, temporal internals ×3,
fixed-weight spatial composites ×3, pipeline reorder ×2, KLT ×2, entropy
back-end ×2). The productive axes were the bias-corrector family (1 promotion
+ the mean tip + 2 corners from 5 slots) and the joint-solve/MST corners.

Gap to offline references (bits/sample = 16/ratio): zstd-19 is beaten on all
four sets. LZMA is beaten on OTB (−27.9%) and CapgMyo (−13–14%) but leads on
**Hyser (+12.28%, 9.596 vs 10.774 b/s)** and **CEMHSEY (+4.43%)** — see §4 for
why that lead is mostly artifact.

*(Bookkeeping flag from this review: `experiments/020_lms4v2_….md` internally
titles itself "# 017"/"Cycle: 16" — numbering drift; content matches CYCLE_LOG
row 21. Cycle 2 has no experiment file, as row 13 notes.)*

## 3. SOTA comparison — nervous-system data, verified against primary sources

**Normalization convention:** coded bits/sample against the *real* ADC
resolution, not the container. Ratios on b-bit data stored in 16-bit words
carry up to 16/b of free padding; ratios on oversampled signals (1 kHz EEG,
30 kS/s AP band) harvest sample-to-sample correlation that critically-sampled
2 kHz sEMG does not contain. This project: Hyser 1.4851× = 10.77 b/s, OTB
2.1934× = 7.29 b/s, mean 1.747× = 9.16 b/s, fully lossless, causal, ~0.12 of
the M7 budget.

### 3.1 Surface EMG (the exact signal class)

| result (verified) | data | honest reading |
|---|---|---|
| **Itiki 2014** (BioMed Eng OnLine 13:25) — the only published HD-sEMG lossless study: best 59.29±1.21% size reduction = **2.46×**, lossless JPEG on **single-differential** gastrocnemius at 20% MVC (verification correction: not monopolar — monopolar was used only for the lossy case); falls to 1.93× at 80% MVC; trapezius 1.47–1.58× | 12-bit, 2048 Hz, 63–127 ch grids | Best case is low-force 12-bit; its *active* numbers are below this repo's on 16-bit words. Force-dependence confirms the activity-entropy floor. **Does not beat this project normalized.** |
| **Biagetti et al. 2021** (Sensors 21:5065; verification correction: UnivPM/ENSTA, not Fraunhofer) — FLAC-0 on nRF52840: 2.50× worst case during contraction | 24-bit ADC, ~<16 effective bits, 800 Hz, 3 ch | Container padding; the repo's own FLAC baseline (0.98–1.23× on true 16-bit) is what remains without it. |
| **Chanasabaeng 2012** (BMEiCON) — LPC-based lossless EMG for embedded | paywalled | CR unverifiable; the thinness of this literature is itself the finding. |

### 3.2 The strongest multichannel biosignal coders (EEG/ECG — easier signals)

| result (verified) | cost | honest reading |
|---|---|---|
| **Capurro et al. 2017** (IEEE JBHI; arXiv 1605.04418) — sequential RLS + coding-tree **single reference channel** + adaptive Golomb: 16-bit EEG 5.21–5.42 b/s (~2.95–3.07×), PTB ECG 4.78 b/s (3.35×); **their reference-channel scheme beat full MV-AR(3) by >0.4 b/s and MV-AR(6) by 0.1 b/s** | MSP432 port: ~154 000 cyc/sample-ch | The academic SOTA — and direct published validation of this repo's rank-1 causal-reference design over full matrixing. Ratio delta vs this repo is signal entropy (1 kHz EEG is 5–10× oversampled), not machinery. ~700× this repo's cycle cost. |
| **Dufort et al. 2018** (TBioCAS) — embedded MCS: 5.34–5.47 b/s lossless on 16-bit 1 kHz EEG, MSP432 ≈1000 cyc/sample-ch, ~400 B/ch | ~1000 cyc/sample-ch | Best like-for-like *embedded* multichannel coder: ~2.9–3.0× on oversampled EEG at ~14× this repo's Hyser cycle cost. |
| **Rzepka 2020** (BSPC 57:101705) — switched LP + cross-channel pairs + ANS, ECG: 2.92–3.43× | "low-complexity", no cycle counts | Mechanism twin of `xchan_bestpartner`; ratios ride ECG's inter-beat baseline. |
| ECG plateau, verified: Jia et al. 2020 (context bias cancellation + adaptive Rice) 2.975–3.040×; Koo 2023 ALP+GR 3.16× on 16-bit 1 kHz PTB; **Deepu 2014 (JSSC, verification correction: not TBioCAS) ASIC 2.25× at 535 nW/ch** | ASIC-class | Adaptive short-order LP + Golomb-Rice tops out ~2.8–3.5× on ECG. Same coder family; lower-entropy signal. |
| **Wongsawat 2006 / IntSKLT 2015** — full reversible KLT matrixing for EEG | O(m²)/sample | The "stronger mechanism" that did *not* become SOTA — superseded by reference-channel prediction (above), supporting P3. |

### 3.3 Broadband neural data (the future 30 kS/s regime)

| result (verified) | container-honest | reading |
|---|---|---|
| **mtscomp** (IBL, delta+zlib) "nearly 3×" | 10-bit-in-int16 → **1.88× honest** | Deployed practice is *below* this repo's mean; compression happens offline, never on the headstage. |
| **Buccino et al. 2023** (J Neural Eng) — best lossless: WavPack 3.59× (NP1), 2.26× (NP2) | NP1 = 10-bit → 2.24×; NP2 = 14-bit → **1.98× honest** | The definitive offline benchmark; this repo's OTB 2.19× on honest 16-bit is at parity with unconstrained WavPack. Their "LSB correction significantly improves CR" is the published twin of §4's lattice finding. |
| **Neuralink Compression Challenge 2024** — zip 2.2×; brainwire delta+adaptive-Rice 3.35×; CMIX ≈3.57× (147 309 568 → 41 263 405 B, encode.su); Spikey learned 3.513×; community noise cap ~5.3× | 10-bit non-uniformly upscaled to 16-bit → best ≈ **2.23× honest**, cap ≈ 3.3× | Context mixing + learned prediction bought **+6.6%** over delta+adaptive Rice at ~10⁵–10⁶× compute. Cross-thread correlation was "vital" (Spikey) — third independent confirmation of P1. The 200× target was the lossy spike pipeline. |
| **22 nm 68-ch SoC** (Frontiers/arXiv 2407.09166) — DPCM2 + Golomb/AC engines: AP 63% SSR lossless (2.70×, AC engine; Golomb slightly lower — verification correction), ~31 cyc/sample-ch, 0.87 µW/ch | native 9-bit, no padding | The closest published silicon to this repo's mechanism set — and strictly *simpler* (DPCM2 + one-tap cross-channel). Fits the 125-cyc budget with 4× margin. |
| **Sensors 2022 IGLOO-nano delta+Huffman** (Intan RHD2132, 30 kS/s): 2.09× offline / 1.52× online — **after discarding 3 LSBs** (near-lossless) | — | The most directly comparable embedded system is below this repo's fully-lossless numbers even with 3 bits discarded. 585 FPGA cells confirms Spartan-7-class feasibility. |
| **Park/Yoon JSSC 2018**: LFP 5.35×, spikes 10.54× (verification correction to the 4.3–5.8 secondary quote); spike path lossy. **imec NCT 2024**: "11.4× loss-less" = 7-bit deltas, <23% NRMSE — **not bit-exact** | — | Implant headlines above ~3× are band-split or event-based and not PCM-lossless; not valid comparisons. |

### 3.4 Learned / exotic ("larger shifts" candidates), verified

- **Chinchilla-70B as compressor** (ICLR 2024): 16-bit LibriSpeech to 16.4% vs
  FLAC 30.3% — real, but raw rate disregarding the 70B model, on speech
  (deep long-range structure); Trilobyte (Interspeech 2026) finds LM gains
  "become more modest as bit depth increases beyond 8-bit" — the exact regime
  of 16-bit noisy sensors.
- **NNCP v3.2 / cmix**: enwik 1.17–1.19 bpb; decode 2.8 / 7.4 days per GB
  (LTCB-verified). 4–6 orders of magnitude past budget. No published
  cmix/paq8/zpaq numbers on EMG/EEG int16 waveforms exist — running them once
  on this corpus would be a novel, cheap calibration.
- **L3TC** (AAAI 2025): smallest competitive learned-lossless line — still
  phone-class silicon at 1.3 MB/s decode, text-only.
- **Small NN over linear on biosignals** (Sriraam 2012, verification
  correction: single-author, gains 10–20% not "~11%", on 12-bit 173 Hz EEG,
  LZ-arithmetic stage): most of the gain came from bias/context correction
  this repo already ships (P9). Transferable expectation on 2 kHz whitened
  sEMG residual: low single digits.
- **RKLT / RWA group reversible integer transforms** (hyperspectral lossless
  SOTA, IEEE TGRS 2016; integer-KLT-for-EEG exists): the one published
  *mechanism* upgrade path over pairwise prediction — a few percent where
  correlation is strong, ~8–16 MACs/sample-ch (estimate) with backward
  adaptation. Contradicts nothing in P3 (which killed *fixed/stale* and
  *2-channel rotation* forms; a periodically re-estimated 8–16-ch lifting
  transform with per-parent fitted gains is the P1b-compatible corner).
- **Sprintz** (IMWUT 2018): MCU-native; its zero-run/low-activity block modes
  are the cheap borrowable piece.
- **Cortex-M55/M85 + Ethos-U55 / STM32N6**: at 128 ch × 2048 Hz the NPU-class
  parts allow ~10⁴–10⁵ ops/sample-ch — small learned predictors become
  *feasible*; the expected *gain* stays small (above). Hardware roadmap, not
  an algorithm win.
- **Near-lossless L∞** (WavPack hybrid: 7.04–7.08× vs 3.6× lossless on
  Neuropixels with spike sorting unaffected — Buccino 2023): the single
  biggest available multiplier (~2×) **if the delivery contract ever relaxes**.
  Scope change, flagged, not a lossless win.

## 4. Measured headroom on this corpus (fresh measurements, 2026-08-25)

Method: offline anchors (lzma/bz2/zstd-22 over several layouts), per-channel
first-order (Miller–Madow) symbol entropies, a non-causal whole-signal
least-squares oracle (4 own lags + 8 grid neighbours, float, rounded),
a faithful pipeline approximation (causal best-of-4 LS subtract + order-4
sign-sign LMS ported from `embedded_codec.py`), and conditional-entropy tests
on the residuals. 15 000 samples/set. Key results:

| set | current best | best offline anchor found | delta-symbol entropy ratio | notes |
|---|---:|---|---:|---|
| hyser | 1.4851× | lzma -9e on time-delta **1.692×** | **2.14–2.18×** | **~50-count lattice, ~460 distinct values/ch** (independently re-verified: median unique-value gap exactly 50) |
| otb | 2.1934× | bz2 on sdelta+tdelta 2.049× | 1.88–1.89× | dense alphabet — codec already beats every offline anchor **and** the linear oracle (2.004×) |
| capgmyo | 1.3531× | 1.211× | 1.36× | dense; codec far ahead of all offline tools |
| cemhsey | 1.9553× | bz2 on sdelta+tdelta **2.227×** | **2.20–2.26×** | **~8-count lattice** (from `_adc16` rescaling of already-quantized mV data) |

Three levers, in measured order of size:

1. **Lattice / alphabet (~85% of the total apparent headroom — and mostly a
   corpus artifact).** On Hyser, plain per-channel time-delta has ~7.3–7.5 bits
   of symbol entropy (implied 2.14–2.18×) while the LMS-alone residual has
   **11.8 bits** — the pipeline's fixed-point arithmetic *fills in* the lattice
   before coding. This, not superior modeling, is most of LZMA's Hyser/CEMHSEY
   lead. A uniform divide-by-step is not exactly invertible (0/128 and 2/320
   channels pass), so exploitation would need per-channel symbol dictionaries.
   **Recommendation: treat this as a corpus-honesty problem, not a codec
   opportunity** — re-derive Hyser/CEMHSEY as true ADC digital codes (the
   Buccino LSB-correction / brainwire dequantization precedent), re-run the
   bench, and re-baseline every reference. Expect the LZMA gap to largely
   close and FLAC to stop expanding; the RHD2164's native stream has no such
   lattice, so nothing deployable is lost.
2. **Context-conditioned entropy coding (real, survives everything).** On the
   pipeline-approximation residual, conditioning on a 4-level bucket of the
   own-channel 4-lag energy `Σ|e[t−1..t−4]|` removes **0.095 / 0.155 / 0.422 /
   0.061 bits/sample** (hyser/otb/capgmyo/cemhsey) — and **0.083–0.387 bits of
   the same structure survives the perfect non-causal linear oracle**, so it is
   genuine amplitude-modulation (heteroscedasticity) structure that no
   predictor can remove. The codec also pays +0.25 bits over its own
   residual's memoryless entropy on CapgMyo. Implied reachable: CapgMyo
   ~1.40–1.42×, OTB ~2.24×; mean **~+2–4%**. Note on P5: the retired `xctx`
   conditioned Rice-k on a **cross-channel** energy context (which the
   predictor had already whitened — measured partner-context MI here is only
   0.018–0.187 bits); the **own-history** energy context was never tried for
   the *k/scale* and carries 2–5× more MI. A LOCO-style per-context adaptive
   k (A[q]/N[q] counters, divisionless, zero side-info) on that context is a
   legitimate new candidate that does not re-propose the dead end.
3. **Better prediction: nearly exhausted (confirmed).** The shipped codec
   already **beats** the non-causal whole-signal linear oracle on OTB (2.193×
   vs 2.004×) and sits within 0.25 bits of it on CapgMyo; measured Rice
   overhead vs its own residual's memoryless entropy is only −0.07…+0.25
   bits/sample across the four sets. "Rice at the floor" holds *for the
   residual as produced* — the loss is in what the residual *is* (lever 1),
   plus the conditional-variance structure (lever 2).

Honest caveats: first-order entropies ignore residual time-dependence (bounded
above by the conditional tests at ≤0.42 bits under the tested contexts); the
oracle bounds only fixed global linear prediction; a real adaptive coder pays
~0.2 bits/sample of learning redundancy on Hyser-sized alphabets; the pipeline
approximation is not the exact shipped codec (its bias corrector + adaptive
Rice already code *below* the approximation's entropy on OTB).

## 5. `embedded_ok` audit — findings and ranked proposals

### Findings

- **The gate is 100% self-reported and has never fired.** Every input
  (`enc_ops`, `causal`, `integer_only`, `state_bytes_per_ch`, `lookahead`) is
  a hand-written literal in `registry.py`; nothing derives from or checks the
  code. All 33 registrations passed. `dec_ops` is computed then unused;
  `block_size` is dead; `n_ch` is hard-coded to 128 while the datasets span
  64–320.
- **`--strict` is wired nowhere.** `.claude/hooks/verify_codec.py` runs only
  round-trip self-tests; there is no CI; `.claude/workflows/compression-cycle.js`
  and `agents/verifier.md` run the audit **without** `--strict` and instruct
  verifiers that the known whole-signal-beta failure is "an already-documented,
  accepted caveat" — a grandfather clause with **no allowlist mechanism**, so a
  *new* offline-parameter codec would get the same free pass. 15 registered
  codecs (including the headline `LMS4bc` and the OTB record-holder `bcpool`)
  fail `--strict` today.
- **Bug: the adaptive-family streaming check is vacuous.**
  `embedded_verify.py:106` computes
  `xa.encode(x[:, :T0]) == xa.encode(xf[:, :T0])` — but `xf` differs from `x`
  only at `t ≥ T0`, so both operands are the *same array*; the check proves
  determinism, not the prefix/streaming property, and `early_changed=0` is
  hard-coded. The "STREAMS (HONEST)" verdict for the backward-adaptive family
  is asserted, not tested.
- **Declared op counts range from honest to ~10× off.** `_BC_XTRA = 22` is
  roughly right (~24–28 real); `_BP_SELECT_OPS = 8` is ~**40–150** real
  ops/sample-ch once the 4-candidate scored scan (two dot products + rounded
  divide + zigzag + `_best_k` per candidate) is counted. This doesn't threaten
  the roomy 1831-cyc sEMG gate but **invalidates `neural_ok` (125 cyc) for the
  whole bestpartner family as currently declared.** Audit 2's own counter also
  undercounts (`_best_k` computes `(u>>k).sum()` twice per iteration), and
  `_BC_STATE` prices accumulators as int32 while the code holds int64.
- **`fpga_ok` exists only as a printout**, infers predictor order from the
  codec *name*, and is stored nowhere.

### Ranked proposals (S/M/L effort)

1. **Wire `--strict` into the PostToolUse hook + verify phase, with an explicit
   waiver ledger** (S, high value): add `research/embedded_waivers.json`
   naming the 15 grandfathered codecs with reasons; `--strict` fails only on
   non-waived hits; append the command to `verify_codec.py`'s SELFTESTS and
   the workflow verifier text. Turns existing detection into enforcement.
2. **Fix the vacuous check and generalize the prefix test to every codec**
   (S–M, high): real invariant — encode `prefix‖futureA` vs `prefix‖futureB`
   and require identical prefix-attributable output for **all**
   `list_codecs()`, not two hardwired families; drive the functional-trace
   patch list from a declared `offline_helpers` set.
3. **Measured-not-declared op counts fed back into `cost`** (M, highest
   absolute): counting twins for the ~10 shared primitives, per-op-class
   tallies {add, mul, div, shift, cmp, mem}, persist `results/measured_ops.json`,
   fail `--strict` when measured > declared × 1.5, and let `score()` use
   `max(declared, measured)`. Immediately settles `neural_ok` honestly.
4. **Per-op-class cycle weights** (S): `{alu:1, mac:1, div:8, branch:2.5,
   mem:2}` — SDIV-heavy fits and branchy bit-packing stop hiding under the
   flat 1.2 cyc/op. Pairs with #3.
5. **Promote `fpga_ok` to a first-class `CostScore` column** (S): move audit
   3's XC7S25 model into `embedded_cost.py`, take order from declared
   metadata (`mac_order`), print in `--selftest` and the leaderboard.
6. **Adversarial worst-case throughput + expansion bound** (M): encode
   full-range noise/step/DC-jump blocks, gate on per-block *max* cycles and
   max emitted bits/sample; require a raw-block escape hatch. The corpus never
   exercises the data-dependent Rice unary/k-search worst case; the device
   will.
7. **Measured state layout** (M) and per-dataset `n_ch` in `score()`.
8. **Hygiene** (S): report-only `dec_cycles` column; delete or use
   `block_size`.

Highest value-per-effort: **#1 + #2 + #4**; #3 is the "real fix" the repo's
own verification doc already calls for.

## 6. Recommended next-cycle agenda (ranked)

1. **Corpus-honesty pass** (changes everything downstream, cheap): re-derive
   Hyser/CEMHSEY as native digital codes (or per-channel lattice indices),
   hash-pin, re-run the bench, re-baseline all references, update the
   LEADERBOARD provenance note. Expect: LZMA gap mostly closes; FLAC stops
   expanding; the honest remaining gap is what levers 2–3 of §4 can reach.
2. **Gate work #1+#2+#4 from §5**, and stop quoting `neural_ok` for the
   bestpartner family until #3 lands.
3. **One offline ceiling probe, run once**: paq8px (16-bit stationary-audio
   model), zpaq -m5, and optionally cmix on 1-minute excerpts of all four
   (normalized) sets. If the best lands <5% above the codec, the local optimum
   is effectively global for lossless on this corpus and the plateau is
   formally closed.
4. **New candidate — per-context adaptive Rice k on the own-history energy
   context** (LOCO A[q]/N[q] discipline, divisionless, zero side-info):
   targets the measured 0.06–0.42 bits/sample of surviving conditional
   structure; biggest expected win on CapgMyo (its bias-stage family already
   wins there). Distinct from retired `xctx` (cross-channel context, P5) —
   document the distinction in the experiment file.
5. **New candidate — 8–16-channel backward-adapted reversible integer lifting
   transform (RKLT/RWA-style, one fitted DoF per parent)** on the high-MI sets
   with the `acar_sel` channel-count gate: the one published mechanism-class
   upgrade over pairwise prediction (hyperspectral lossless SOTA). Expected
   +3–8% on OTB/CEMHSEY, ~0 on CapgMyo — budget accordingly.
6. **Write-up**: the honest-normalization audit (§3's container/bit-depth/
   oversampling corrections) is itself publishable — no ephys compression
   paper states it cleanly, and this repo now has the data to.

*Cross-agent verification note: 36 literature claims were fact-checked; every
compression number quoted here survived primary-source verification; the five
corrections found (Itiki montage, Deepu venue, Jia authorship, Biagetti
affiliation, FDSOI engine attribution) are applied above. The lattice finding
(§4) was measured twice independently (workflow agent + orchestrator re-run)
with matching results.*

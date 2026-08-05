# 017 — The ACTUAL paper model: bGPT-audio (110M) zero-shot on our HD-sEMG

- **Cycle:** external-model probe (the literal LMCompress audio model; no codec promoted)
- **Date:** 2026-08-03
- **Branch:** `claude/lm-compression-probe`
- **Candidate:** `bgpt-audio` — the 110M-param model LMCompress uses for audio, run zero-shot
- **Datasets:** otb_hdsemg_vl (64 ch), hyser_1dof_f1_s1 (128 ch)
- **Tool:** `research/bgpt_probe.py` (needs `torch`, `transformers`, `samplings`, the
  [sander-wood/bgpt](https://github.com/sanderwood/bgpt) repo, and `weights-audio.pth`)

## Motivation

015/016 used *small, on-domain* models (MLP, Transformer) as a headroom ceiling. Fair
follow-up challenge: **run the paper's actual model.** LMCompress's audio path is **bGPT-audio**
— a 110M-param hierarchical byte Transformer (12-layer patch decoder + 3-layer byte decoder,
hidden 768, 8192-byte context) **pretrained on ~1000 h of 8-bit LibriSpeech**. bGPT predicts a
distribution over the next byte, so `model(patches, masks).loss` (bits/byte) **is** the arithmetic-
coding code length — no coder needed. We feed our EMG as bytes, teacher-forced (one forward per
8160-byte chunk), and read off the rate.

Two serializations (bGPT-audio is a **mono, 8-bit** model, so its fair peer is our *temporal-only*
`LMS+Rice`, and the cross-channel champion is the overall target):
- **16-bit little-endian (LOSSLESS)** — the apples-to-apples number vs our lossless codecs.
- **8-bit per-channel min-max (LOSSY)** — bGPT's *in-distribution best case* (matches its 8-bit
  audio training); NOT a lossless solution for our data, shown to give the model its fair due.

## Measurement (`results/bgpt_zeroshot.csv`; 64/128 chunks of 4080 samp/ch, ~2 s/chunk CPU)

**16-bit LOSSLESS — directly comparable to our codec:**

| dataset | delta+Rice | **LMS+Rice** (fair peer) | champion `LMS4+xchan_bp` | **bGPT-audio 110M zero-shot** |
|---|--:|--:|--:|--:|
| otb_hdsemg_vl | 1.982× | 1.987× | **2.401×** | **1.076×**  (−45.8 % vs LMS+Rice) |
| hyser_1dof_f1_s1 | 1.334× | 1.342× | **1.490×** | **1.070×**  (−20.3 % vs LMS+Rice) |

bGPT-audio reaches only ~7.45 bits/byte (of 8 raw) → it barely compresses at all. 16-bit
interleaved bytes (a slowly-varying high byte + a near-noise low byte) are **far out of
distribution** for an 8-bit audio model.

**8-bit LOSSY — bGPT's in-distribution best case (not a lossless solution; ratios vs 8-bit raw):**

| dataset | delta+Rice | LMS+Rice | champion | **bGPT-audio 110M zero-shot** |
|---|--:|--:|--:|--:|
| otb_hdsemg_vl (8-bit) | 1.473× | 1.329× | **1.898×** | **1.527×**  (**+14.9 % vs LMS+Rice**) |

In its native format bGPT-audio's "understanding" is **real**: 5.24 bits/byte, beating both
per-channel temporal codecs — qualitatively the paper's audio result. But it is **lossy**, and it
**still loses to our cross-channel champion** (1.527× vs 1.898×) because it is mono and cannot see
across channels.

## Verdict

1. **On the actual lossless task, the actual paper model fails** (~1.07×, worse than `delta+Rice`).
   Zero-shot bGPT-audio does not transfer to 16-bit lossless HD-sEMG.
2. **Its power is real, but mis-matched to our problem.** Given its native 8-bit input it beats
   per-channel temporal coding by ~15 % — but (a) 8-bit is lossy, not our task, and (b) it still
   loses to our codec, which wins on the **cross-channel** axis bGPT structurally lacks.
3. **Together with 015/016 this closes the loop.** A *domain-matched* model (our on-domain MLP /
   Transformer) only **ties** the champion; the *actual paper model* (huge but domain-mismatched,
   mono, 8-bit) is **worse**. The paper's own thesis — domain match dominates — predicts exactly
   this, and a domain-matched large model is **ill-posed here** (no HD-sEMG pretraining corpus;
   4 recordings can't fine-tune 110M). Scale is not the missing ingredient; cross-channel structure
   and embedded feasibility are, and those are what `LMS4+xchan_bp` already has.
4. 110M params, ~2 s/chunk on CPU, float transcendentals ⇒ `embedded_ok = NO` by orders of magnitude.

## Caveats

- **Zero-shot, not fine-tuned.** Fine-tuning bGPT-audio on EMG could raise the 8-bit number, but
  can't make the 16-bit-lossless byte format less OOD without retraining, and can't add a cross-
  channel mechanism to a mono model.
- **Mono** (no cross-channel), **bounded sample** (one 8160-byte chunk per channel), **8-bit is
  lossy**. All noted; none changes the lossless verdict.

## Conclusion for the project

The LMCompress idea is sound and its model is genuinely predictive on in-distribution data — but it
does not beat `LMS4+Rice+xchan_bestpartner` on lossless HD-sEMG, and it is not embeddable. The only
lead this whole line of work surfaced remains 015/016's: a **cheap integer nonlinear cross-channel**
primitive on differential arrays, chased inside `embedded_ok`.

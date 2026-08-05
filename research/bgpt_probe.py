#!/usr/bin/env python3
"""
bgpt_probe.py -- run the ACTUAL 110M bGPT-audio (LMCompress's audio model),
zero-shot, on our HD-sEMG, and report its lossless compression rate.

bGPT (sander-wood/bgpt) is a byte model: it predicts a distribution over the next
byte, so its cross-entropy in bits/byte IS the arithmetic-coding code length
(model.forward(patches, masks).loss is that CE).  We feed our int16 EMG as bytes,
run the model teacher-forced (one forward per <=8160-byte chunk -- no generation
loop), and read off bits/byte -> bits/sample -> ratio.

bGPT-audio is a *mono* model pretrained on 8-bit 16 kHz LibriSpeech.  So:
  * each EMG channel is serialized as its own mono byte stream (per-channel),
  * its fair peer is our TEMPORAL-ONLY codec (LMS+Rice); the cross-channel
    champion (LMS4+xchan_bestpartner) is the overall target it would need to beat.
  * 16-bit little-endian bytes are OUT of distribution for an 8-bit-audio model
    (expected: poor).  --bits 8 additionally measures a LOSSY 8-bit-quantized
    version -- bGPT's in-distribution best case, NOT comparable to lossless.

Usage:
  python3 bgpt_probe.py --weights weights-audio.pth --bgpt ./bgpt \
      --dataset otb_hdsemg_vl --channels 64 --samples 4080 --bits 16
"""
import argparse, math, os, sys, time
import numpy as np
import torch

LN2 = math.log(2.0)


def load_bgpt(weights, bgpt_dir):
    sys.path.insert(0, bgpt_dir)
    import utils  # noqa  (reads PATCH_SIZE etc. from config; defaults match audio model)
    from transformers import GPT2Config
    ck = torch.load(weights, map_location="cpu", weights_only=False)
    sd = ck["model"] if "model" in ck else ck
    # infer dims straight from the checkpoint (don't trust config.py)
    patch_size = sd["patch_level_decoder.patch_embedding.weight"].shape[1] // (256 + 1)
    patch_len = sd["patch_level_decoder.base.wpe.weight"].shape[0]
    byte_pos = sd["byte_level_decoder.base.transformer.wpe.weight"].shape[0]
    hidden = sd["patch_level_decoder.base.wpe.weight"].shape[1]
    print(f"  checkpoint: PATCH_SIZE={patch_size} PATCH_LENGTH={patch_len} "
          f"byte_pos={byte_pos} hidden={hidden}")
    utils.PATCH_SIZE = patch_size
    pc = GPT2Config(num_hidden_layers=12, max_length=patch_len,
                    max_position_embeddings=patch_len, hidden_size=hidden,
                    n_head=hidden // 64, vocab_size=1)
    bc = GPT2Config(num_hidden_layers=3, max_length=byte_pos,
                    max_position_embeddings=byte_pos, hidden_size=hidden,
                    n_head=hidden // 64, vocab_size=256 + 1)
    model = utils.bGPTLMHeadModel(pc, bc)
    missing, unexpected = model.load_state_dict(sd, strict=False)
    miss = [m for m in missing if "attn.bias" not in m and "attn.masked_bias" not in m]
    if miss:
        print(f"  !! missing (non-buffer) keys: {miss[:6]}{'...' if len(miss) > 6 else ''}")
    model.eval()
    n = sum(p.numel() for p in model.parameters())
    print(f"  loaded bGPT: {n/1e6:.1f}M params")
    return model, patch_size, patch_len


def make_chunk(byte_list, patch_size, patch_len, ext="wav"):
    """Replicates bgpt read_bytes(): bos(ext)-patch + body + eos-patch, pad, cap."""
    ext_b = list(bytearray(ext, "utf-8"))[:patch_size]
    b = list(byte_list)
    if len(b) % patch_size:
        b += [256] * (patch_size - len(b) % patch_size)
    bos = ext_b + [256] * (patch_size - len(ext_b))
    b = bos + b + [256] * patch_size
    b = b[:patch_len * patch_size]
    masks = [1] * (len(b) // patch_size)
    return torch.tensor(b, dtype=torch.long), torch.tensor(masks, dtype=torch.long)


def serialize(samples, bits):
    """channel samples -> byte list.  16: lossless int16 LE 2-byte; 8: uint8
    (samples are assumed already quantised to 0..255 by quantize8)."""
    if bits == 16:
        return list(np.ascontiguousarray(samples.astype("<i2")).tobytes())
    return list(np.ascontiguousarray(samples).astype(np.uint8).tobytes())


def quantize8(x):
    """Per-channel min-max to uint8 (LOSSY), kept as int16 for the registry codecs."""
    out = np.empty_like(x, dtype=np.int16)
    for c in range(x.shape[0]):
        lo, hi = int(x[c].min()), int(x[c].max())
        out[c] = np.round((x[c].astype(np.float64) - lo) / max(1, hi - lo) * 255).astype(np.int16)
    return out


@torch.no_grad()
def bgpt_bits_per_byte(model, x, patch_size, patch_len, bits, max_chunks, verbose):
    C, N = x.shape
    body = (patch_len - 2) * patch_size                 # bytes of real data per chunk
    spb = 2 if bits == 16 else 1                        # bytes per sample
    per_chan = max(1, body // (spb * 1))                # bytes/chunk -> samples handled below
    losses, done, t0 = [], 0, time.perf_counter()
    for c in range(C):
        if done >= max_chunks:
            break
        raw = serialize(x[c], bits)                     # all bytes of channel c
        for s in range(0, len(raw), body):
            if done >= max_chunks:
                break
            seg = raw[s:s + body]
            if len(seg) < body // 2:                    # skip a short tail segment
                continue
            patches, masks = make_chunk(seg, patch_size, patch_len)
            loss = model(patches.unsqueeze(0), masks.unsqueeze(0)).loss.item()
            losses.append(loss / LN2)                   # bits per byte
            done += 1
            if verbose and done % 10 == 0:
                print(f"    chunk {done}/{max_chunks}  bits/byte {np.mean(losses):.4f}  "
                      f"({(time.perf_counter()-t0)/done:.1f}s/chunk)")
    bpb = float(np.mean(losses))
    return bpb, done, spb, time.perf_counter() - t0


def baselines(x, raw_bits, names=("delta+Rice", "LMS+Rice", "LMS4+Rice+xchan_bestpartner")):
    import registry as reg
    xc = np.ascontiguousarray(x)
    out = {}
    for nm in names:
        c = reg.REGISTRY.get(nm)
        if c:
            blob = c.encode(xc, cols=16)
            out[nm] = raw_bits / (len(blob) * 8.0 / xc.size)   # ratio vs raw @ this depth
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--bgpt", required=True)
    ap.add_argument("--repo", default="/home/user/hdemg-lossless-compression")
    ap.add_argument("--dataset", default="otb_hdsemg_vl")
    ap.add_argument("--channels", type=int, default=64)
    ap.add_argument("--samples", type=int, default=4080)
    ap.add_argument("--bits", type=int, default=16, choices=[8, 16])
    ap.add_argument("--max-chunks", type=int, default=64)
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(args.repo, "host_tools"))
    sys.path.insert(0, os.path.join(args.repo, "research"))
    import datasets as dsmod

    torch.set_num_threads(4)
    print(f"== bGPT-audio zero-shot on {args.dataset} ({args.bits}-bit) ==")
    model, ps, pl = load_bgpt(args.weights, args.bgpt)

    ds = {d.name: d for d in dsmod.corpus()}[args.dataset]
    x, _ = ds.load(max_samples=0)
    x = np.ascontiguousarray(x[:args.channels, :args.samples])
    if args.bits == 8:
        x = quantize8(x)                               # LOSSY per-channel 8-bit
    raw_bits = 8 * (2 if args.bits == 16 else 1)       # raw depth we compress against
    print(f"  sample: {x.shape[0]} ch x {x.shape[1]} samp  (raw {raw_bits}-bit)")

    bpb, n, spb, secs = bgpt_bits_per_byte(model, x, ps, pl, args.bits, args.max_chunks, True)
    bps = bpb * spb                                     # bits per sample
    ratio = raw_bits / bps                              # == 8 / bits_per_byte
    base = baselines(x, raw_bits)

    depth = "LOSSLESS 16-bit" if args.bits == 16 else "LOSSY 8-bit (not lossless-comparable)"
    print(f"\n  ---- {args.dataset}: {n} chunks, {secs:.0f}s  [{depth}] ----")
    print(f"    {'model':<34}{'bits/samp':>10}{'ratio':>8}")
    for nm, r in base.items():
        tag = " (temporal-only, fair peer)" if nm == "LMS+Rice" else (
              " (cross-channel champion)" if "xchan" in nm else "")
        print(f"    {nm:<34}{raw_bits/r:>10.3f}{r:>7.3f}x{tag}")
    lbl = f"bGPT-audio 110M zero-shot ({args.bits}b)"
    print(f"    {lbl:<34}{bps:>10.3f}{ratio:>7.3f}x")
    fair = base.get("LMS+Rice")
    if fair:
        print(f"    -> bGPT-audio {'beats' if ratio>fair else 'loses to'} even temporal-only "
              f"LMS+Rice by {100*(ratio/fair-1):+.1f}%  (bits/byte {bpb:.3f} of 8 raw)")

    if args.csv:
        import csv
        new = not os.path.exists(args.csv)
        with open(args.csv, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["dataset", "bits", "model", "bits_per_sample", "ratio", "chunks"])
            for nm, r in base.items():
                w.writerow([args.dataset, args.bits, nm, f"{raw_bits/r:.4f}", f"{r:.4f}", ""])
            w.writerow([args.dataset, args.bits, "bgpt_audio_110M_zeroshot",
                        f"{bps:.4f}", f"{ratio:.4f}", n])
        print(f"  wrote {args.csv}")


if __name__ == "__main__":
    raise SystemExit(main())

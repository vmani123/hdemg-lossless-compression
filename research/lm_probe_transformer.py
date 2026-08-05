#!/usr/bin/env python3
"""
lm_probe_transformer.py  --  on-domain autoregressive *Transformer* headroom probe.

Faithful follow-up to `lm_probe.py` (which used a small MLP).  This replaces the
MLP with a real causal **Transformer** (nanoGPT-style: multi-head self-attention +
pre-LN MLP blocks) so the probe actually tests the two things the MLP could not:
**long-range temporal attention** (context 256 vs the MLP's order-8 window) and
**depth**.  It is still measured as ideal code length (held-out NLL in bits/sample,
`bits = -log2 p_theta(d[c,t] | causal context)`), so no arithmetic coder is needed.

This is NOT the paper's model either -- LMCompress uses a 110M-param Transformer
(bGPT-audio) *pretrained on ~1000 h of audio*.  This is a small model trained
from scratch on *our own* HD-sEMG corpus.  That is the deliberate, defensible test
for our regime: there is no large HD-sEMG pretraining corpus, and the paper's own
lesson is that domain match dominates, so an on-domain (if small) model is the fair
probe of whether a Transformer finds structure our linear LMS4+xchan codec misses.

Causality / losslessness (same contract as lm_probe.py): predicting d[c,t] uses
  * this channel's own past deltas d[c, <t]         (via the causal Transformer)
  * the K nearest lower-index channels AT t          d[c-1..c-K, t]  (concurrent,
                                                       decodable under channel-raster
                                                       order: decode timestep t in
                                                       channel order 0..C-1)
  * a learned projection of all channels' PREVIOUS delta  d[:, t-1]
All strictly decodable before x[c,t]; encoder and decoder share the fixed weights.

Not deployable (huge vs embedded_ok) -- this measures a *ceiling*, ships no codec.

Run:
    python3 research/lm_probe_transformer.py --selftest
    python3 research/lm_probe_transformer.py --datasets hyser_1dof_f1_s1 capgmyo_dba_s1 \
            --csv results/lm_probe_transformer.csv
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host_tools"))
import datasets as dsmod            # noqa: E402
import registry as reg             # noqa: E402

import torch                       # noqa: E402
import torch.nn as nn             # noqa: E402
import torch.nn.functional as F   # noqa: E402

LN2 = math.log(2.0)
BASELINES = ["delta+Rice", "LMS+Rice", "LMS4+Rice+xchan_bestpartner"]


# ---- discretised-logistic log-pmf over integers (stable), torch/autograd ----
def disc_logistic_logpmf(d, mu, ls):
    s = torch.exp(ls.clamp(-12.0, 12.0))
    A = (d + 0.5 - mu) / s
    B = (d - 0.5 - mu) / s
    logsA = F.logsigmoid(A)
    logsB = F.logsigmoid(B)
    u = (logsB - logsA).clamp(max=-1e-7)          # <= 0 since A > B
    log1m = torch.where(u > -LN2, torch.log(-torch.expm1(u)), torch.log1p(-torch.exp(u)))
    return (logsA + log1m).clamp(min=math.log(1e-12))


# ------------------------------- the model --------------------------------
class Block(nn.Module):
    def __init__(self, d, heads, drop=0.0):
        super().__init__()
        self.ln1 = nn.LayerNorm(d)
        self.attn = nn.MultiheadAttention(d, heads, dropout=drop, batch_first=True)
        self.ln2 = nn.LayerNorm(d)
        self.mlp = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))

    def forward(self, x, mask):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, attn_mask=mask, need_weights=False)
        x = x + a
        x = x + self.mlp(self.ln2(x))
        return x


class TxnProbe(nn.Module):
    """Causal Transformer over a channel's delta stream + cross-channel side info."""
    def __init__(self, C, d_model=64, n_layer=4, n_head=4, neighbors=4, proj=16,
                 scale=1.0):
        super().__init__()
        self.C, self.K = C, neighbors
        # data delta-scale: inputs are pre-divided by it; outputs are multiplied
        # back, so the head only ever emits O(1) values (mu_raw~0, ls_raw~0 =>
        # mu~0, s~scale at init -- a sane starting distribution).
        self.register_buffer("scale", torch.tensor(float(scale)))
        self.register_buffer("logscale", torch.tensor(math.log(float(scale))))
        self.embed = nn.Linear(1, d_model)                 # scalar delta -> d_model
        self.pos = nn.Parameter(torch.zeros(1, 4096, d_model))
        self.blocks = nn.ModuleList([Block(d_model, n_head) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(d_model)
        self.lag_proj = nn.Linear(C, proj)                 # all-channel previous delta
        self.head = nn.Sequential(
            nn.Linear(d_model + neighbors + proj, d_model), nn.GELU(),
            nn.Linear(d_model, 2))
        self.head[-1].bias.data = torch.zeros(2)
        self.head[-1].weight.data *= 0.1                   # small init -> stable start

    def forward(self, inp_std, conc_std, lag_std):
        """All three inputs are already divided by `scale` (O(1)).  inp (B,L,1) own
        deltas; conc (B,L,K) concurrent nbrs at the TARGET step; lag (B,L,C) all
        channels' previous delta.  Returns (mu, ls) each (B,L) in ORIGINAL units:
        the prediction for the next delta at each position."""
        B, L, _ = inp_std.shape
        x = self.embed(inp_std) + self.pos[:, :L]
        mask = torch.triu(torch.full((L, L), float("-inf")), diagonal=1)
        for blk in self.blocks:
            x = blk(x, mask)
        h = self.ln_f(x)                                   # (B,L,d) : h[i] saw inp[:i+1]
        side = torch.cat([h, conc_std, self.lag_proj(lag_std)], dim=-1)
        out = self.head(side)
        mu = out[..., 0] * self.scale                      # back to original units
        ls = out[..., 1] + self.logscale                   # s ~ scale at init
        return mu, ls


# ----------------------------- data plumbing ------------------------------
def deltas(x):
    d = np.zeros_like(x, dtype=np.float32)
    d[:, 1:] = np.diff(x.astype(np.float32), axis=1)
    return d


def sample_windows(d, C, N, L, K, lo, hi, n, rng):
    """n windows starting in [lo, hi-L).  Returns tensors for the model plus the
    integer targets.  Target at output position i is d[c, t0+i+1]."""
    cs = rng.integers(0, C, n)
    t0 = rng.integers(lo, hi - L - 1, n)
    inp = np.empty((n, L, 1), np.float32)
    tgt = np.empty((n, L), np.float32)
    conc = np.zeros((n, L, K), np.float32)
    lag = np.empty((n, L, C), np.float32)
    for b in range(n):
        c, s = int(cs[b]), int(t0[b])
        inp[b, :, 0] = d[c, s:s + L]
        tgt[b] = d[c, s + 1:s + 1 + L]                     # next-step target
        for j in range(1, K + 1):
            if c - j >= 0:
                conc[b, :, j - 1] = d[c - j, s + 1:s + 1 + L]   # concurrent (target step)
        lag[b] = d[:, s:s + L].T                           # previous step, all channels
    return inp, tgt, conc, lag


def to_t(*arrs):
    return [torch.from_numpy(a) for a in arrs]


# ------------------------------- train/eval -------------------------------
def probe(x, name, L=256, d_model=64, n_layer=4, n_head=4, neighbors=4,
          steps=1500, batch=32, lr=5e-4, warmup=32, eval_windows=1200,
          holdout=0.30, seed=0, verbose=True):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    C, N = x.shape
    d = deltas(x)
    split = int(N * (1.0 - holdout))
    scale = float(d[:, :split].std()) + 1.0            # delta-scale: standardises
    #                                                    inputs and de-normalises outputs
    model = TxnProbe(C, d_model, n_layer, n_head, neighbors, scale=scale)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    model.train()
    t0 = time.perf_counter()
    for step in range(1, steps + 1):
        inp, tgt, conc, lag = sample_windows(d, C, N, L, neighbors, 0, split, batch, rng)
        inp_t, tgt_t, conc_t, lag_t = to_t(inp / scale, tgt, conc / scale, lag / scale)
        mu, ls = model(inp_t, conc_t, lag_t)
        nll = -disc_logistic_logpmf(tgt_t[:, warmup:], mu[:, warmup:], ls[:, warmup:])
        loss = nll.mean() / LN2                            # bits/sample
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if verbose and (step % max(1, steps // 6) == 0 or step == 1):
            print(f"    [{name}] step {step:5d}/{steps}  train bits/sample {loss.item():6.3f}")

    # -------- held-out eval on the tail --------
    model.eval()
    tot, cnt = 0.0, 0
    with torch.no_grad():
        done = 0
        while done < eval_windows:
            b = min(batch, eval_windows - done)
            inp, tgt, conc, lag = sample_windows(d, C, N, L, neighbors, split, N, b, rng)
            inp_t, tgt_t, conc_t, lag_t = to_t(inp / scale, tgt, conc / scale, lag / scale)
            mu, ls = model(inp_t, conc_t, lag_t)
            nll = -disc_logistic_logpmf(tgt_t[:, warmup:], mu[:, warmup:], ls[:, warmup:]) / LN2
            tot += float(nll.sum()); cnt += nll.numel(); done += b
    bpp = tot / cnt
    params = sum(p.numel() for p in model.parameters())
    return dict(name=name, C=C, N=N, split=split, bpp=bpp, ratio=16.0 / bpp,
                params=params, eval_pairs=cnt, train_s=time.perf_counter() - t0)


def baseline_tail(x, split, names=BASELINES):
    tail = np.ascontiguousarray(x[:, split:])
    out = {}
    for nm in names:
        c = reg.REGISTRY.get(nm)
        if c is None:
            continue
        blob = c.encode(tail, cols=16)
        bpp = len(blob) * 8.0 / tail.size
        out[nm] = dict(bpp=bpp, ratio=16.0 / bpp)
    return out


def selftest():
    ok = True
    # pmf normalises
    grid = torch.arange(-4000, 4001).float()
    for mu, ls in [(0.0, 2.0), (30.0, 5.0), (-12.0, 1.0)]:
        tot = torch.exp(disc_logistic_logpmf(grid, torch.full_like(grid, mu),
                                             torch.full_like(grid, ls))).sum().item()
        print(f"  pmf sum (mu={mu:+.1f}, s={math.exp(ls):.1f}) = {tot:.6f}")
        ok &= abs(tot - 1.0) < 1e-3
    # forward/backward runs, finite loss, grads flow
    torch.manual_seed(0)
    m = TxnProbe(C=16, d_model=32, n_layer=2, n_head=4, neighbors=4, proj=8)
    inp = torch.randn(4, 64, 1); conc = torch.randn(4, 64, 4); lag = torch.randn(4, 64, 16)
    tgt = torch.randint(-20, 20, (4, 64)).float()
    mu, ls = m(inp, conc, lag)
    loss = (-disc_logistic_logpmf(tgt, mu, ls)).mean()
    loss.backward()
    gnorm = math.sqrt(sum(float((p.grad**2).sum()) for p in m.parameters() if p.grad is not None))
    print(f"  forward loss {loss.item():.4f} bits*ln2, grad-norm {gnorm:.3e} (finite & flowing)")
    ok &= math.isfinite(loss.item()) and gnorm > 0
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--datasets", nargs="+", default=["hyser_1dof_f1_s1", "capgmyo_dba_s1"])
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--context", type=int, default=256, dest="L")
    ap.add_argument("--d-model", type=int, default=64)
    ap.add_argument("--layers", type=int, default=4)
    ap.add_argument("--heads", type=int, default=4)
    ap.add_argument("--neighbors", type=int, default=4)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--eval-windows", type=int, default=1200, dest="eval_windows")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--csv", default="")
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    if args.selftest:
        return selftest()

    sets = {ds.name: ds for ds in dsmod.corpus()}
    rows = []
    for name in args.datasets:
        ds = sets.get(name)
        if ds is None:
            print(f"!! unknown dataset {name!r}"); continue
        x, _ = ds.load(max_samples=args.max_samples)
        x = np.ascontiguousarray(x)
        print(f"\n=== {name}  ({x.shape[0]} ch x {x.shape[1]} samp) ===")
        r = probe(x, name, L=args.L, d_model=args.d_model, n_layer=args.layers,
                  n_head=args.heads, neighbors=args.neighbors, steps=args.steps,
                  batch=args.batch, lr=args.lr, eval_windows=args.eval_windows, seed=args.seed)
        base = baseline_tail(x, r["split"]); r["baselines"] = base
        rows.append(r)
        champ = base.get("LMS4+Rice+xchan_bestpartner")
        print(f"  ---- held-out tail ({r['eval_pairs']:,} sample-ch, {r['train_s']:.0f}s train, "
              f"{r['params']/1e3:.0f}k params) ----")
        print(f"    {'model':<32}{'bits/samp':>10}{'ratio':>8}{'embed_ok':>10}")
        for bn, bv in base.items():
            print(f"    {bn:<32}{bv['bpp']:>10.3f}{bv['ratio']:>7.3f}x{'yes':>10}")
        print(f"    {'LM-probe Transformer (learned)':<32}{r['bpp']:>10.3f}{r['ratio']:>7.3f}x{'NO':>10}")
        if champ:
            dpc = 100.0 * (r["ratio"] / champ["ratio"] - 1.0)
            print(f"    -> Transformer {'BEATS' if dpc>0 else 'loses to'} champion by {dpc:+.1f}%  "
                  f"(ctx {args.L}, {r['params']/1e3:.0f}k params => embedded_ok NO)")

    if args.csv and rows:
        import csv
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "ch", "samples", "model", "bits_per_sample", "ratio", "embedded_ok"])
            for r in rows:
                for bn, bv in r["baselines"].items():
                    w.writerow([r["name"], r["C"], r["N"], bn, f"{bv['bpp']:.4f}", f"{bv['ratio']:.4f}", "yes"])
                w.writerow([r["name"], r["C"], r["N"], "lm_probe_transformer",
                            f"{r['bpp']:.4f}", f"{r['ratio']:.4f}", "no"])
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

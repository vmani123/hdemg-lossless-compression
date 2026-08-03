#!/usr/bin/env python3
"""
lm_probe.py  --  "LMCompress"-style learned-model ceiling probe for HD-EMG.

Tests the central claim of *Lossless data compression by large models*
(Li et al., Nat. Mach. Intell. 2025): a better autoregressive model of the data
compresses it better, because the achievable lossless code length **is** the
model's cross-entropy on the data,

        bits(x) = sum_t -log2 p_theta(x_t | x_<t)        (arithmetic coding
                                                          realises this to within
                                                          ~2 bits *total*).

So we can measure the ratio a learned model would achieve WITHOUT building an
arithmetic coder at all: just fit an autoregressive predictor and report its
held-out negative log-likelihood in bits/sample.  This is the cheap, decisive
"is there headroom?" experiment for bringing a large-model front-end to our data.

WHAT IS THE "MODEL" HERE
    A small MLP (pure numpy -- the repo has no torch) that maps a *causal*
    context to the parameters of a discretised-logistic distribution over the
    next-sample delta d[c,t] = x[c,t] - x[c,t-1]:

        context = [ d[c, t-1 .. t-P] ]            (P past deltas of this channel)
               ++ [ d[:,  t-1] ]                  (ALL channels' previous delta --
                                                   full cross-channel spatial
                                                   context, strictly at t-1)
        (mu, log_s) = MLP(context)
        p(d[c,t])   = sigma((d+0.5-mu)/s) - sigma((d-0.5-mu)/s)

    Everything in the context is strictly earlier than t, so the model is a
    legitimate causal codec front-end (encoder and decoder share the fixed,
    pretrained weights and the past -- exactly LMCompress's setup).  The MLP is
    strictly more informed than our LMS4+xchan champion (nonlinear, sees every
    channel), so if it CANNOT beat the champion, that is a strong negative.

WHAT THIS IS NOT
    Not a deployable codec.  The MLP costs ~H*(P+C) MACs per sample-channel
    (hundreds of x our champion's ~53 ops), needs float exp/sigmoid, and would
    need bit-exact-deterministic inference at both ends to actually be lossless.
    Its ratio is reported with embedded_ok = NO, exactly as the leaderboard flags
    the offline-float +xchan numbers.  This probe measures HEADROOM, not a win.

Run:
    python3 research/lm_probe.py --selftest                 # verify grads + pmf
    python3 research/lm_probe.py                            # hyser + otb
    python3 research/lm_probe.py --datasets hyser_1dof_f1_s1 otb_hdsemg_vl \
            cemhsey_s1_d1t1 capgmyo_dba_s1 --csv results/lm_probe.csv
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

LN2 = math.log(2.0)
BASELINES = ["delta+Rice", "LMS+Rice", "LMS4+Rice+xchan_bestpartner"]


# ===========================================================================
# Discretised logistic: stable log-pmf over integers, and its analytic grads.
# ===========================================================================
def _logsigmoid(z):
    # log sigmoid(z) = -softplus(-z), stable for all z.
    return -np.logaddexp(0.0, -z)


def disc_logistic_logpmf(d, mu, ls):
    """log P(d) for integer d under Logistic(mu, s=exp(ls)), binned to unit width.

    p = sigma(A) - sigma(B),  A=(d+.5-mu)/s > B=(d-.5-mu)/s.
    Computed as sigma(A)-sigma(B) = exp(logsA)*(1-exp(logsB-logsA)) so it stays
    stable in the tails (where the naive subtraction underflows).
    """
    s = np.exp(np.clip(ls, -12.0, 12.0))
    inv = 1.0 / s
    A = (d + 0.5 - mu) * inv
    B = (d - 0.5 - mu) * inv
    logsA = _logsigmoid(A)
    logsB = _logsigmoid(B)
    u = logsB - logsA                      # <= 0 since A > B
    u = np.minimum(u, -1e-12)
    # log1mexp(u) = log(1 - exp(u)), stable split at u ~ -ln2.
    log1m = np.where(u > -LN2, np.log(-np.expm1(u)), np.log1p(-np.exp(u)))
    logp = logsA + log1m
    return np.maximum(logp, math.log(1e-12))   # floor: cap a single sample ~40 bits


def disc_logistic_grads(d, mu, ls):
    """d(NLL_nats)/d(mu), d(NLL_nats)/d(ls) for NLL = -log p.  Returns (gmu, gls)."""
    s = np.exp(np.clip(ls, -12.0, 12.0))
    inv = 1.0 / s
    A = (d + 0.5 - mu) * inv
    B = (d - 0.5 - mu) * inv
    sigA = 1.0 / (1.0 + np.exp(-A))
    sigB = 1.0 / (1.0 + np.exp(-B))
    p = np.maximum(sigA - sigB, 1e-12)
    dpA = sigA * (1.0 - sigA)              # sigma'(A)
    dpB = sigB * (1.0 - sigB)              # sigma'(B)
    # dp/dmu = -(1/s)(sigma'(A)-sigma'(B)); dNLL/dmu = -(1/p) dp/dmu
    gmu = (dpA - dpB) / (p * s)
    # dp/dls = -(A sigma'(A) - B sigma'(B)); dNLL/dls = -(1/p) dp/dls
    gls = (A * dpA - B * dpB) / p
    return gmu, gls


# ===========================================================================
# Tiny MLP:  features -> (mu, ls).  One hidden ReLU layer.
# ===========================================================================
def mlp_init(in_dim, hidden, init_ls, rng):
    return dict(
        W1=(rng.standard_normal((in_dim, hidden)) * math.sqrt(2.0 / in_dim)).astype(np.float64),
        b1=np.zeros(hidden),
        W2=(rng.standard_normal((hidden, 2)) * 0.01).astype(np.float64),
        b2=np.array([0.0, init_ls]),          # mu~0, log-scale ~ log(std of deltas)
    )


def mlp_forward(P, F):
    z1 = F @ P["W1"] + P["b1"]
    h = np.maximum(z1, 0.0)
    out = h @ P["W2"] + P["b2"]
    return out[:, 0], out[:, 1], (z1, h, F)


def mlp_backward(P, cache, gmu, gls):
    z1, h, F = cache
    B = F.shape[0]
    d_out = np.stack([gmu, gls], axis=1) / B          # mean over batch
    g = dict(
        W2=h.T @ d_out,
        b2=d_out.sum(0),
    )
    dh = d_out @ P["W2"].T
    dz1 = dh * (z1 > 0.0)
    g["W1"] = F.T @ dz1
    g["b1"] = dz1.sum(0)
    return g


# ===========================================================================
# Feature extraction (causal): build (features, target) from deltas.
# ===========================================================================
def deltas(x):
    """x int (C,N) -> d float (C,N), d[:,0]=0, d[:,t]=x[:,t]-x[:,t-1]."""
    d = np.zeros_like(x, dtype=np.float64)
    d[:, 1:] = np.diff(x.astype(np.float64), axis=1)
    return d


def gather(d, order, c_idx, t_idx, neighbors=4):
    """Feature rows for targets (c_idx[i], t_idx[i]).  Needs t_idx >= order+1.

    Context (all strictly decodable before x[c,t] under channel-raster order --
    decode timestep t in channel order 0..C-1, so lower-index channels at time t
    are already known):
      * temporal   : this channel's own last `order` deltas   d[c, t-1..t-order]
      * CONCURRENT : the K nearest lower-index channels at time t  d[c-1..c-K, t]
                     -- same-timestep spatial context, the dominant HD-EMG
                     redundancy and exactly what xchan_bestpartner exploits.
                     (index runs down each grid column, so c-1 is the vertical
                     electrode neighbour.)  Zeroed where c-k < 0.
      * lagged     : ALL channels' previous delta  d[:, t-1]  (cheap extra ctx)
    """
    B = c_idx.shape[0]
    temporal = np.empty((B, order))
    for k in range(1, order + 1):
        temporal[:, k - 1] = d[c_idx, t_idx - k]
    conc = np.empty((B, neighbors))
    for j in range(1, neighbors + 1):
        cj = c_idx - j
        conc[:, j - 1] = np.where(cj >= 0, d[np.clip(cj, 0, None), t_idx], 0.0)
    cross = d[:, t_idx - 1].T                     # (B, C): all channels at t-1
    F = np.concatenate([temporal, conc, cross], axis=1)
    tgt = d[c_idx, t_idx]
    return F, tgt


# ===========================================================================
# Train + evaluate on one dataset.
# ===========================================================================
def probe_dataset(x, name, order=8, neighbors=4, hidden=64, steps=4000, batch=4096,
                  lr=5e-3, eval_pairs=300_000, holdout=0.30, seed=0, verbose=True):
    C, N = x.shape
    rng = np.random.default_rng(seed)
    d = deltas(x)
    split = int(N * (1.0 - holdout))
    lo_t = order + 1

    # standardisation from a sample of train pairs
    n_std = min(50_000, C * (split - lo_t))
    cs = rng.integers(0, C, n_std)
    ts = rng.integers(lo_t, split, n_std)
    Fs, tg = gather(d, order, cs, ts, neighbors)
    fmu = Fs.mean(0)
    fsd = Fs.std(0) + 1e-6
    init_ls = math.log(tg.std() + 1.0)

    def norm(F):
        return (F - fmu) / fsd

    P = mlp_init(order + neighbors + C, hidden, init_ls, rng)
    # Adam state
    m = {k: np.zeros_like(v) for k, v in P.items()}
    v = {k: np.zeros_like(v) for k, v in P.items()}
    b1a, b2a, eps = 0.9, 0.999, 1e-8

    t0 = time.perf_counter()
    for step in range(1, steps + 1):
        cs = rng.integers(0, C, batch)
        ts = rng.integers(lo_t, split, batch)
        F, tgt = gather(d, order, cs, ts, neighbors)
        F = norm(F)
        mu, ls, cache = mlp_forward(P, F)
        gmu, gls = disc_logistic_grads(tgt, mu, ls)
        g = mlp_backward(P, cache, gmu, gls)
        gn = math.sqrt(sum(float((gg * gg).sum()) for gg in g.values())) + 1e-12
        scale = min(1.0, 5.0 / gn)               # global-norm clip
        for k in P:
            gk = g[k] * scale
            m[k] = b1a * m[k] + (1 - b1a) * gk
            v[k] = b2a * v[k] + (1 - b2a) * (gk * gk)
            mhat = m[k] / (1 - b1a ** step)
            vhat = v[k] / (1 - b2a ** step)
            P[k] -= lr * mhat / (np.sqrt(vhat) + eps)
        if verbose and (step % max(1, steps // 5) == 0 or step == 1):
            bits = -disc_logistic_logpmf(tgt, mu, ls).mean() / LN2
            print(f"    [{name}] step {step:5d}/{steps}  train bits/sample {bits:6.3f}")

    # ---- held-out eval on the tail (context may reach before split; fine) ----
    n_eval = min(eval_pairs, C * (N - split))
    cs = rng.integers(0, C, n_eval)
    ts = rng.integers(split, N, n_eval)
    F, tgt = gather(d, order, cs, ts, neighbors)
    mu, ls, _ = mlp_forward(P, norm(F))
    nll_bits = -disc_logistic_logpmf(tgt, mu, ls) / LN2
    bpp = float(nll_bits.mean())
    train_s = time.perf_counter() - t0

    macs = hidden * (order + neighbors + C) + hidden * 2      # ~ MACs / sample-channel
    return dict(name=name, C=C, N=N, split=split, bpp=bpp, ratio=16.0 / bpp,
                macs=macs, params=sum(vv.size for vv in P.values()),
                eval_pairs=n_eval, train_s=train_s)


def baseline_tail(x, split, names=BASELINES):
    """Real registry codecs on the SAME held-out tail -> (bits/sample, ratio)."""
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


# ===========================================================================
# Self-test: pmf normalises, and analytic grads match finite differences.
# ===========================================================================
def selftest():
    ok = True
    rng = np.random.default_rng(1)
    # (1) pmf sums to ~1 over the integer grid for random (mu, ls)
    grid = np.arange(-4000, 4001)
    for _ in range(5):
        mu = rng.uniform(-50, 50)
        ls = rng.uniform(1.0, 6.0)
        total = np.exp(disc_logistic_logpmf(grid, np.full_like(grid, mu, float),
                                            np.full_like(grid, ls, float))).sum()
        print(f"  pmf sum (mu={mu:+7.2f}, s={math.exp(ls):8.1f}) = {total:.6f}")
        ok &= abs(total - 1.0) < 1e-3
    # (2) analytic (gmu, gls) vs finite differences
    d = rng.integers(-30, 30, 2000).astype(float)
    mu = rng.uniform(-10, 10, 2000)
    ls = rng.uniform(1.5, 4.0, 2000)
    gmu, gls = disc_logistic_grads(d, mu, ls)
    h = 1e-5
    fd_mu = (-disc_logistic_logpmf(d, mu + h, ls) + disc_logistic_logpmf(d, mu - h, ls)) / (2 * h)
    fd_ls = (-disc_logistic_logpmf(d, mu, ls + h) + disc_logistic_logpmf(d, mu, ls - h)) / (2 * h)
    emu = np.abs(gmu - fd_mu).max()
    els = np.abs(gls - fd_ls).max()
    print(f"  grad check  max|dmu err|={emu:.2e}  max|dls err|={els:.2e}")
    ok &= emu < 1e-4 and els < 1e-4
    # (3) end-to-end MLP grad vs FD on a couple of weights
    in_dim, H, B = 12, 5, 64
    P = mlp_init(in_dim, H, 2.0, rng)
    F = rng.standard_normal((B, in_dim))
    tgt = rng.integers(-20, 20, B).astype(float)

    def loss(Pp):
        mu, ls, _ = mlp_forward(Pp, F)
        return (-disc_logistic_logpmf(tgt, mu, ls) / LN2).mean()

    mu, ls, cache = mlp_forward(P, F)
    gmu, gls = disc_logistic_grads(tgt, mu, ls)
    g = mlp_backward(P, cache, gmu, gls)
    g = {k: gg / LN2 for k, gg in g.items()}       # loss measured in bits
    worst = 0.0
    for k in ("W1", "W2", "b1", "b2"):
        idx = tuple(rng.integers(0, s) for s in P[k].shape)
        base = P[k][idx]
        P[k][idx] = base + h; lp = loss(P)
        P[k][idx] = base - h; lm = loss(P)
        P[k][idx] = base
        fd = (lp - lm) / (2 * h)
        err = abs(fd - g[k][idx])
        worst = max(worst, err)
        print(f"  MLP grad {k}{idx}: analytic {g[k][idx]:+.6e}  fd {fd:+.6e}  err {err:.2e}")
    ok &= worst < 1e-5
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="verify pmf + gradients, then exit")
    ap.add_argument("--datasets", nargs="+", default=["hyser_1dof_f1_s1", "otb_hdsemg_vl"])
    ap.add_argument("--max-samples", type=int, default=0, help="0 = full record")
    ap.add_argument("--order", type=int, default=8)
    ap.add_argument("--neighbors", type=int, default=4, help="concurrent lower-index channel context")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=5e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    sets = {ds.name: ds for ds in dsmod.corpus()}
    rows = []
    for name in args.datasets:
        ds = sets.get(name)
        if ds is None:
            print(f"!! unknown dataset {name!r}; known: {list(sets)}")
            continue
        x, grid = ds.load(max_samples=args.max_samples)
        x = np.ascontiguousarray(x)
        print(f"\n=== {name}  ({x.shape[0]} ch x {x.shape[1]} samp, {x.nbytes/1e6:.1f} MB) ===")
        r = probe_dataset(x, name, order=args.order, neighbors=args.neighbors, hidden=args.hidden,
                          steps=args.steps, batch=args.batch, lr=args.lr, seed=args.seed)
        base = baseline_tail(x, r["split"])
        r["baselines"] = base
        rows.append(r)
        champ = base.get("LMS4+Rice+xchan_bestpartner")
        print(f"  ---- held-out tail ({r['eval_pairs']:,} sample-ch, {r['train_s']:.1f}s train) ----")
        print(f"    {'model':<32}{'bits/samp':>10}{'ratio':>8}{'embed_ok':>10}")
        for bn, bv in base.items():
            print(f"    {bn:<32}{bv['bpp']:>10.3f}{bv['ratio']:>7.3f}x{'yes':>10}")
        print(f"    {'LM-probe (MLP+xchan, learned)':<32}{r['bpp']:>10.3f}{r['ratio']:>7.3f}x{'NO':>10}")
        if champ:
            delta = 100.0 * (r["ratio"] / champ["ratio"] - 1.0)
            verdict = "BEATS champion" if delta > 0 else "loses to champion"
            print(f"    -> learned model {verdict} by {delta:+.1f}%  "
                  f"(neural cost ~{r['macs']:,} MAC/sample-ch vs champion ~53 ops => embedded_ok NO)")

    if args.csv and rows:
        import csv
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "ch", "samples", "model", "bits_per_sample", "ratio", "embedded_ok"])
            for r in rows:
                for bn, bv in r["baselines"].items():
                    w.writerow([r["name"], r["C"], r["N"], bn, f"{bv['bpp']:.4f}", f"{bv['ratio']:.4f}", "yes"])
                w.writerow([r["name"], r["C"], r["N"], "lm_probe", f"{r['bpp']:.4f}", f"{r['ratio']:.4f}", "no"])
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

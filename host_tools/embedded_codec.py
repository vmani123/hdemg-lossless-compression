#!/usr/bin/env python3
"""
embedded_codec.py  -  Faithful software model of the hardware-implementable
lossless codecs for the HD-EMG node. Shared by bench_lossless.py (Stage 4) and
verify_compressed.py (Stage 5).

All codecs here are integer-exact and one-pass / streaming-legal (no look-ahead
beyond a small block), i.e. portable to RTL/firmware later:

  * delta1  : order-1 DPCM (predict x[t] ~ x[t-1])
  * lms     : backward-adaptive sign-sign LMS linear predictor (order M),
              the streaming way to approach FLAC's LPC without look-ahead
  * cross   : optional cross-channel front-end -- subtract a physical grid
              neighbour (a fixed spanning tree over the electrode array) before
              the temporal predictor. This is the lever to beat per-channel FLAC.

Entropy back-end is adaptive Golomb-Rice (per-block k). Everything round-trips
bit-exact; run `python3 embedded_codec.py` to self-test.
"""
import struct
import numpy as np

MAGIC = 0x5243  # 'RC'
BLOCK = 256     # Rice adaptive-k block size (samples)

PRED_DELTA = 0
PRED_LMS = 1
LMS_ORDER = 8
LMS_SHIFT = 8   # fixed-point weight scale


# ---------------------------------------------------------------------------
# zigzag map (signed <-> unsigned), vectorized
# ---------------------------------------------------------------------------
def zigzag(s):
    s = s.astype(np.int64)
    return ((s << 1) ^ (s >> 63)).astype(np.uint64)


def unzigzag(u):
    u = u.astype(np.uint64)
    return ((u >> np.uint64(1)).astype(np.int64) ^ -(u & np.uint64(1)).astype(np.int64))


# ---------------------------------------------------------------------------
# Adaptive Golomb-Rice for a 1-D residual array
# ---------------------------------------------------------------------------
def _best_k(u_block):
    n = u_block.size
    if n == 0:
        return 0
    best_k, best_len = 0, None
    for k in range(0, 20):
        length = int((u_block >> np.uint64(k)).sum()) + n * (1 + k)
        if best_len is None or length < best_len:
            best_len, best_k = length, k
        # sum(q) shrinks fast; once it stops helping we can stop
        if (u_block >> np.uint64(k)).sum() == 0:
            break
    return best_k


def rice_encode_1d(res):
    """Encode a 1-D int array -> bytes (self-describing)."""
    u = zigzag(res)
    n = u.size
    nblocks = (n + BLOCK - 1) // BLOCK
    ks = np.zeros(nblocks, np.uint8)
    all_bits = []
    for b in range(nblocks):
        ub = u[b * BLOCK:(b + 1) * BLOCK]
        k = _best_k(ub)
        ks[b] = k
        q = (ub >> np.uint64(k)).astype(np.int64)
        r = (ub & np.uint64((1 << k) - 1)).astype(np.int64) if k else np.zeros(ub.size, np.int64)
        lengths = q + 1 + k
        total = int(lengths.sum())
        starts = np.concatenate(([0], np.cumsum(lengths)[:-1]))
        bits = np.zeros(total, np.uint8)
        bits[starts + q] = 1                      # unary stop bit
        for j in range(k):                        # k remainder bits, MSB first
            bits[starts + q + 1 + j] = (r >> (k - 1 - j)) & 1
        all_bits.append(bits)
    bit_arr = np.concatenate(all_bits) if all_bits else np.zeros(0, np.uint8)
    packed = np.packbits(bit_arr).tobytes()
    hdr = struct.pack('<IH', n, BLOCK) + ks.tobytes() + struct.pack('<I', len(packed))
    return hdr + packed


def rice_decode_1d(buf, off=0):
    """Decode -> (int array, new_offset)."""
    n, bs = struct.unpack_from('<IH', buf, off); off += 6
    nblocks = (n + bs - 1) // bs
    ks = np.frombuffer(buf, np.uint8, nblocks, off); off += nblocks
    (plen,) = struct.unpack_from('<I', buf, off); off += 4
    bits = np.unpackbits(np.frombuffer(buf, np.uint8, plen, off)); off += plen

    out = np.zeros(n, np.int64)
    pos = 0
    ones = np.flatnonzero(bits)      # positions of 1-bits (stop bits + remainder bits)
    optr = 0
    idx = 0
    for b in range(nblocks):
        k = int(ks[b])
        cnt = min(bs, n - b * bs)
        # pass 1: find stop bits + remainder starts (O(symbols))
        qs = np.empty(cnt, np.int64)
        rstart = np.empty(cnt, np.int64)
        for i in range(cnt):
            while ones[optr] < pos:
                optr += 1
            stop = ones[optr]
            qs[i] = stop - pos
            rstart[i] = stop + 1
            pos = stop + 1 + k
            # advance optr past any 1-bits inside this symbol's remainder field
            while optr < ones.size and ones[optr] < pos:
                optr += 1
        # pass 2: gather k-bit remainders vectorized
        r = np.zeros(cnt, np.int64)
        for j in range(k):
            r |= bits[rstart + j].astype(np.int64) << (k - 1 - j)
        u = (qs << k) | r
        out[idx:idx + cnt] = u
        idx += cnt
    return unzigzag(out.astype(np.uint64)), off


# ---------------------------------------------------------------------------
# Temporal predictors (operate on [C, N] int arrays; vectorized over channels)
# ---------------------------------------------------------------------------
def delta_forward(x):
    res = np.empty_like(x, dtype=np.int64)
    res[:, 0] = x[:, 0]
    res[:, 1:] = np.diff(x.astype(np.int64), axis=1)
    return res


def delta_inverse(res):
    return np.cumsum(res.astype(np.int64), axis=1)


def lms_forward(x, order=LMS_ORDER, shift=LMS_SHIFT):
    C, N = x.shape
    x = x.astype(np.int64)
    w = np.zeros((C, order), np.int64)
    hist = np.zeros((C, order), np.int64)      # past reconstructed samples
    res = np.empty((C, N), np.int64)
    for t in range(N):
        pred = (w * hist).sum(axis=1) >> shift
        e = x[:, t] - pred
        res[:, t] = e
        # sign-sign LMS update (identical in decoder)
        w += np.sign(e)[:, None] * np.sign(hist)
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = x[:, t]
    return res


def lms_inverse(res, order=LMS_ORDER, shift=LMS_SHIFT):
    C, N = res.shape
    res = res.astype(np.int64)
    w = np.zeros((C, order), np.int64)
    hist = np.zeros((C, order), np.int64)
    x = np.empty((C, N), np.int64)
    for t in range(N):
        pred = (w * hist).sum(axis=1) >> shift
        xt = pred + res[:, t]
        x[:, t] = xt
        w += np.sign(res[:, t])[:, None] * np.sign(hist)
        hist[:, 1:] = hist[:, :-1]
        hist[:, 0] = xt
    return x


# ---------------------------------------------------------------------------
# Cross-channel front-end: subtract a grid-neighbour parent (spanning tree).
# parent[c] < c so decode can reconstruct in channel order; root parent = -1.
# ---------------------------------------------------------------------------
def grid_parents(channels, cols):
    parent = np.full(channels, -1, np.int64)
    for g in range(channels):
        r, c = g // cols, g % cols
        if c > 0:
            parent[g] = g - 1          # left neighbour
        elif r > 0:
            parent[g] = g - cols       # up neighbour (first column)
    return parent


CROSS_SHIFT = 8


def int_beta(num, den, shift=CROSS_SHIFT):
    """Fixed-point gain round(num / den * 2**shift) computed on the exact
    rational with ONE integer division and no float: half away from zero,
    0 when den <= 0, clipped to int16. Deterministic on every platform, so
    the C port (hdemg-bench codec/) and the RTL reproduce it bit for bit.
    This is the rule research/registry.py always used for its adaptive and
    best-partner betas; from S1 on it is the family-wide rule."""
    d = int(den)
    if d <= 0:
        return 0
    n = int(num)
    mag = ((abs(n) << shift) + d // 2) // d
    b = -mag if n < 0 else mag
    return max(-32768, min(32767, b))


def cross_betas(x, parent, shift=CROSS_SHIFT):
    """Optimal fixed per-channel gain beta (fixed-point) for predicting a channel
    from its parent: beta ~ <x_c, x_p> / <x_p, x_p>. Sent as tiny side-info
    (one int16 per channel). Adapting the gain -- rather than subtracting the
    neighbour outright -- is what stops the independent noise floor from being
    doubled when correlation is low (beta -> 0), while still cancelling the
    shared spatial signal when correlation is high (beta -> 1<<shift).
    Integer only since hdemg-bench S1 (see int_beta)."""
    x = x.astype(np.int64)
    betas = np.zeros(x.shape[0], np.int64)
    for g in range(x.shape[0]):
        p = parent[g]
        if p < 0:
            continue
        num = int((x[g] * x[p]).sum())
        den = int((x[p] * x[p]).sum())
        betas[g] = int_beta(num, den, shift)
    return betas


def cross_forward(x, parent, betas, shift=CROSS_SHIFT):
    x = x.astype(np.int64)
    y = x.copy()
    for g in range(x.shape[0]):
        p = parent[g]
        if p >= 0:
            y[g] = x[g] - ((betas[g] * x[p]) >> shift)
    return y


def cross_inverse(y, parent, betas, shift=CROSS_SHIFT):
    x = y.astype(np.int64).copy()
    for g in range(y.shape[0]):        # parent[g] < g so parent already restored
        p = parent[g]
        if p >= 0:
            x[g] = y[g] + ((betas[g] * x[p]) >> shift)
    return x


# ---------------------------------------------------------------------------
# Full array codec: header + per-channel Rice of the residual
# ---------------------------------------------------------------------------
def encode(x, predictor=PRED_LMS, cross=False, cols=16):
    C, N = x.shape
    betas = None
    if cross:
        parent = grid_parents(C, cols)
        betas = cross_betas(x, parent)
        xt = cross_forward(x, parent, betas)
    else:
        xt = x.astype(np.int64)
    res = lms_forward(xt) if predictor == PRED_LMS else delta_forward(xt)
    body = b''.join(rice_encode_1d(res[c]) for c in range(C))
    hdr = struct.pack('<HBBHI', MAGIC, predictor, 1 if cross else 0, cols, C) \
        + struct.pack('<I', N)
    if cross:
        hdr += betas.astype('<i2').tobytes()   # C int16 side-info
    return hdr + body


def decode(buf):
    magic, predictor, cross, cols, C = struct.unpack_from('<HBBHI', buf, 0)
    (N,) = struct.unpack_from('<I', buf, 10)
    assert magic == MAGIC, 'bad codec magic'
    off = 14
    betas = None
    if cross:
        betas = np.frombuffer(buf, '<i2', C, off).astype(np.int64); off += 2 * C
    res = np.empty((C, N), np.int64)
    for c in range(C):
        arr, off = rice_decode_1d(buf, off)
        res[c] = arr
    xt = lms_inverse(res) if predictor == PRED_LMS else delta_inverse(res)
    if cross:
        xt = cross_inverse(xt, grid_parents(C, cols), betas)
    return xt.astype(np.int16)


# ---------------------------------------------------------------------------
# Known-answer / independent cross-check tests for the shared Rice coder.
#
# Non-negotiable #4 (no hallucinated correctness): every codec in research/
# registry.py funnels its residual stream through rice_encode_1d/rice_decode_1d,
# so a subtle bug here would silently corrupt every measured ratio at once while
# still passing a plain decode(encode(x))==x round-trip (a paired encoder/decoder
# can share the same bug and still agree with ITSELF). The check below decodes
# rice_encode_1d's actual byte output using a decoder written FROM SCRATCH here,
# independently, with no shared code -- it re-derives the header layout and the
# Golomb-Rice bit convention (q zero-bits, a 1 stop-bit, then k remainder bits
# MSB-first) from this module's own docstring/comments, not by calling
# rice_decode_1d. Agreement between two independently-written implementations is
# real evidence the format is what it claims to be, not just that a function
# round-trips through its own paired inverse.
# ---------------------------------------------------------------------------
def _independent_rice_decode(buf):
    """From-scratch reference Golomb-Rice decoder for rice_encode_1d's on-disk
    format. Deliberately unvectorized (plain Python bit-by-bit) and shares no
    code with rice_decode_1d -- see the module note above for why."""
    n, bs = struct.unpack_from('<IH', buf, 0)
    nblocks = (n + bs - 1) // bs
    off = 6
    ks = list(buf[off:off + nblocks]); off += nblocks
    (plen,) = struct.unpack_from('<I', buf, off); off += 4
    packed = buf[off:off + plen]
    bits = []
    for byte in packed:
        for shift in range(7, -1, -1):     # MSB-first per byte, matches np.unpackbits
            bits.append((byte >> shift) & 1)
    pos = 0
    out = []
    for b in range(nblocks):
        k = ks[b]
        cnt = min(bs, n - b * bs)
        for _ in range(cnt):
            q = 0
            while bits[pos] == 0:
                q += 1
                pos += 1
            pos += 1                        # the stop bit itself
            r = 0
            for _ in range(k):
                r = (r << 1) | bits[pos]
                pos += 1
            u = (q << k) | r
            out.append((u >> 1) ^ -(u & 1))  # unzigzag, done by hand here too
    return out


def _known_answer_tests():
    rng = np.random.default_rng(1234)

    # 1) zigzag/unzigzag: hand-verifiable small values (0->0, -1->1, 1->2, -2->3, ...)
    s = np.array([0, -1, 1, -2, 2, -32768, 32767], dtype=np.int64)
    expected_zz = np.array([0, 1, 2, 3, 4, 65535, 65534], dtype=np.uint64)
    got_zz = zigzag(s)
    assert np.array_equal(got_zz, expected_zz), \
        f"zigzag KAT failed: got {got_zz}, expected {expected_zz}"
    assert np.array_equal(unzigzag(got_zz), s), "unzigzag does not invert zigzag"

    # 2) Rice coder: decode the PRODUCTION encoder's real byte output with an
    # INDEPENDENTLY WRITTEN decoder (no shared code) across varied residual
    # arrays and block-boundary-adjacent lengths -- catches a bug that a
    # same-module round-trip (encode/decode sharing an assumption) would miss.
    test_lengths = [0, 1, BLOCK - 1, BLOCK, BLOCK + 1, 2 * BLOCK + 7]
    for n in test_lengths:
        for scale in (0, 1, 15, 400, 32000):
            res = (rng.normal(0, max(scale, 1), n).round().astype(np.int64)
                   if n else np.zeros(0, np.int64))
            res = np.clip(res, -32768, 32767)
            buf = rice_encode_1d(res)
            got = _independent_rice_decode(buf)
            assert got == list(res), (
                f"independent Rice decoder disagrees with rice_encode_1d's output "
                f"(n={n}, scale={scale}): this means the encoder is not actually "
                f"emitting the Golomb-Rice format it claims to")
            # cross-check against the PRODUCTION decoder too, so a divergence
            # between the two decoders (rather than a real encoder bug) is
            # distinguishable from the assertion above
            prod, _ = rice_decode_1d(buf)
            assert np.array_equal(prod, res), \
                f"rice_decode_1d round-trip mismatch (n={n}, scale={scale})"

    # 3) Degenerate sanity floor: an all-zero residual block must Rice-code to
    # (near) its theoretical minimum -- 1 bit/sample (k=0, q=0 every symbol) plus
    # the small fixed header -- not silently fall back to something larger due to
    # a k-selection bug.
    zeros = np.zeros(4 * BLOCK, np.int64)
    buf = rice_encode_1d(zeros)
    bits_per_sample = (len(buf) - 6 - ((4 * BLOCK + BLOCK - 1) // BLOCK) - 4) * 8 / len(zeros)
    assert bits_per_sample <= 1.05, (
        f"all-zero residual coded at {bits_per_sample:.3f} bits/sample, "
        f"expected ~1.0 -- k-selection or stop-bit logic likely broken")

    # 4) Integer cross-channel gain (hdemg-bench S1, ruling R1): beta is the
    # exact rational num/den scaled by 2**shift, rounded HALF AWAY FROM ZERO,
    # with no float anywhere. Ties are the only inputs where this differs from
    # the old float pipeline (Python round() is half-even): 0.5 -> 1 here, 0 there.
    assert int_beta(0, 0) == 0 and int_beta(5, 0) == 0, "den=0 must give 0"
    assert int_beta(1, 1) == 256, "exact 1.0 -> 256"
    assert int_beta(1, 512) == 1 and int_beta(-1, 512) == -1, "tie 0.5 -> away from zero"
    assert int_beta(3, 512) == 2 and int_beta(-3, 512) == -2, "tie 1.5 -> 2"
    assert int_beta(1, 1024) == 0 and int_beta(1, 1000) == 0, "below half -> 0"
    assert int_beta(2, 1000) == 1, "0.512 -> 1"
    assert int_beta(200, 1) == 32767 and int_beta(-200, 1) == -32768, "clip to int16"
    assert int_beta(7, 3, shift=0) == 2, "shift honoured: 7/3 -> 2"
    # random dot-product-sized inputs: agrees with the float formula everywhere
    # except exact ties, which must land on the away-from-zero side
    for _ in range(2000):
        num = int(rng.integers(-2**38, 2**38))
        den = int(rng.integers(1, 2**38))
        got = int_beta(num, den)
        flt = max(-32768, min(32767, int(round(num / den * 256))))
        tie = (2 * ((abs(num) << 8) % den)) == den
        assert got == flt or tie, f"int_beta({num},{den})={got} vs float {flt}, not a tie"

    print("known-answer tests: zigzag KAT, independent Rice decoder cross-check "
          f"({len(test_lengths)} lengths x 5 scales), all-zero floor -- ALL PASSED")


# ---------------------------------------------------------------------------
def _selftest():
    _known_answer_tests()
    rng = np.random.default_rng(0)
    x = (rng.normal(0, 15, (16, 2000)).round().astype(np.int16))
    x[3, 500:520] += 400   # a spike
    for pred in (PRED_DELTA, PRED_LMS):
        for cross in (False, True):
            b = encode(x, predictor=pred, cross=cross, cols=4)
            y = decode(b)
            ok = np.array_equal(x, y)
            ratio = x.nbytes / len(b)
            print(f"  pred={pred} cross={int(cross)}  round-trip={'OK' if ok else 'FAIL'}"
                  f"  ratio={ratio:.2f}x")
            assert ok, "round-trip mismatch"
    print("embedded_codec self-test: ALL round-trips bit-exact")


if __name__ == '__main__':
    _selftest()

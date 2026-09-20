#!/usr/bin/env python3
"""compare_int_beta.py -- S1 evidence: only codecs that use embedded_codec.cross_betas
may move, and by less than 0.01 % in ratio; every other codec must be byte-identical
in ratio (the registry delegation changed no arithmetic)."""
import csv
import sys

LIMIT_PCT = 0.01


def load(path):
    with open(path, newline="") as f:
        return {(r["dataset"], r["name"]): float(r["ratio"]) for r in csv.DictReader(f)}


def main(before, after):
    b, a = load(before), load(after)
    assert b.keys() == a.keys(), "row sets differ between the two runs"
    bad = 0
    print(f"{'dataset':<20}{'codec':<34}{'before':>10}{'after':>10}{'delta %':>10}")
    for key in sorted(b):
        d = 100.0 * (a[key] / b[key] - 1.0)
        moved = a[key] != b[key]
        uses_cross_betas = "xchan" in key[1]
        if moved and not uses_cross_betas:
            bad += 1
            flag = "  <-- must not move"
        elif abs(d) >= LIMIT_PCT:
            bad += 1
            flag = "  <-- over limit"
        else:
            flag = ""
        if uses_cross_betas or moved:
            print(f"{key[0]:<20}{key[1]:<34}{b[key]:>10.5f}{a[key]:>10.5f}{d:>+10.4f}{flag}")
    print("RESULT:", "PASS" if bad == 0 else f"FAIL ({bad} rows)")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

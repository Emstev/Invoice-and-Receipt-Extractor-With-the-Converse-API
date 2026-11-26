"""compare.py - score each model's output folder against ground_truth.json and print a cost-and-accuracy table.

Usage:  python3 compare.py out/nova-lite-text out/nova-pro-text | tee comparison.md
"""
import json
import re
import sys
from pathlib import Path

FIELDS = ["doc_type", "supplier_name", "supplier_vat_number", "invoice_number", "invoice_date", "due_date",
          "subtotal", "vat_total", "total", "line_count", "line_totals"]


def norm_text(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def same(field, got, want):
    if field in ("subtotal", "vat_total", "total"):
        return isinstance(got, (int, float)) and abs(got - want) <= 0.01
    if field == "line_totals":
        return sorted(round(x, 2) for x in got) == sorted(round(x, 2) for x in want)
    if field == "line_count":
        return got == want
    return norm_text(got) == norm_text(want)    # ignores case, spaces and punctuation


def score(folder, truth):
    right = checked = docs_exact = status_ok = 0
    cost = tin = tout = ms = first_pass = 0
    misses = []
    for name, want in truth.items():
        res = json.loads((Path(folder) / (Path(name).stem + ".json")).read_text())
        got, meta = res["extraction"] or {}, res["meta"]
        lines_got = got.get("line_items") or []
        g = dict(got, line_count=len(lines_got), line_totals=[li.get("line_total", 0) for li in lines_got])
        w = dict(want, line_count=len(want["line_items"]), line_totals=[li["line_total"] for li in want["line_items"]])
        wrong = [f for f in FIELDS if not same(f, g.get(f), w.get(f))]
        right += len(FIELDS) - len(wrong); checked += len(FIELDS)
        docs_exact += not wrong
        status_ok += meta["status"] == want["expected_status"]
        first_pass += meta["status"] == "ok" and meta["attempts"] == 1
        cost += meta["cost_usd"]; tin += meta["input_tokens"]; tout += meta["output_tokens"]; ms += meta["latency_ms"]
        if wrong:
            misses.append(f"{name}: {', '.join(wrong)}")
    n = len(truth)
    return dict(model=Path(folder).name, field_acc=100 * right / checked, docs_exact=docs_exact, n=n,
                status_ok=status_ok, first_pass=first_pass, avg_in=tin / n, avg_out=tout / n,
                cost_doc=cost / n, cost_total=cost, avg_s=ms / n / 1000, misses=misses)


def main():
    truth = json.loads(Path("ground_truth.json").read_text())
    rows = [score(f, truth) for f in sys.argv[1:]]
    print("| Model | Field accuracy | Docs fully correct | Status as expected | Passed first try | "
          "Avg input tokens | Avg output tokens | Cost per doc (USD) | Cost per 1,000 docs | Avg seconds |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['model']} | {r['field_acc']:.1f}% | {r['docs_exact']}/{r['n']} | {r['status_ok']}/{r['n']} | "
              f"{r['first_pass']}/{r['n']} | {r['avg_in']:.0f} | {r['avg_out']:.0f} | ${r['cost_doc']:.5f} | "
              f"${r['cost_doc'] * 1000:.2f} | {r['avg_s']:.1f} |")
    for r in rows:
        print(f"\n**{r['model']} misses:** " + ("; ".join(r["misses"]) or "none"))
    good = [r for r in rows if r["field_acc"] >= 95 and r["status_ok"] == r["n"]]
    pick = min(good, key=lambda r: r["cost_doc"]) if good else max(rows, key=lambda r: r["field_acc"])
    print(f"\nRecommendation: **{pick['model']}** - " +
          ("cheapest model with at least 95% field accuracy and every status as expected."
           if good else "no model met both bars (95% field accuracy AND every status as expected); this one was the most accurate, so keep a human check."))


if __name__ == "__main__":
    main()

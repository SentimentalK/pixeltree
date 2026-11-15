"""Re-apply the oracles to the archived end state of every episode (R1).

Each episode keeps its sandbox home (`<episode dir>/sbx/home`, the state the oracle read after the app was closed),
so an oracle can be re-applied without running the agent again.  Use it to
  * prove the stored grades are reproducible (`--check`: the current oracles must give the stored `ok` for every row),
  * grade with a corrected oracle version (writes <out>/episodes_<tag>.jsonl: same rows, `ok` / `oracle_detail` from
    the current oracles, plus `ok_stored` / `oracle_detail_stored`; summarize.py / compare.py read it via --rows).

  python -m bench.agent.regrade out/r1/formal --check            # v1 reproduces
  python -m bench.agent.regrade out/r1/formal --oracles v1_1 --tag v1_1
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.agent.summarize import load_rows  # noqa: E402
from bench.env import oracles_v1_1, registry  # noqa: E402

ORACLES = {"v1": registry.oracle, "v1_1": oracles_v1_1.oracle}


def regrade(rows, oracle=registry.oracle):
    """[(row, ok, detail)] for every non-error row, `oracle` applied to <dir>/sbx/home."""
    out = []
    for r in rows:
        if r.get("stop_reason") == "error":
            continue
        home = Path(r["dir"]) / "sbx" / "home"
        if not home.is_dir():
            out.append((r, None, f"no archived home at {home}"))
            continue
        try:
            ok, detail = oracle(r["task"], home)
        except Exception as exc:  # noqa: BLE001  (reported, not raised)
            ok, detail = None, f"oracle raised {type(exc).__name__}: {exc}"
        out.append((r, None if ok is None else bool(ok), str(detail)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--oracles", choices=sorted(ORACLES), default="v1")
    ap.add_argument("--check", action="store_true", help="exit 1 unless every stored ok is reproduced")
    ap.add_argument("--tag", default=None, help="write <out>/episodes_<tag>.jsonl with the re-applied grades")
    args = ap.parse_args(argv)
    rows = load_rows(args.out)
    graded = regrade(rows, ORACLES[args.oracles])
    changed = [(r, ok, d) for r, ok, d in graded if ok != bool(r["ok"])]
    print(f"{len(graded)} episodes re-graded with oracles {args.oracles}, {len(changed)} differ from the stored grade")
    for r, ok, d in changed:
        print(f"  {r['task']} {r['cond']} r{r['rep']}: stored ok={r['ok']} -> {ok}  [{d[:150]}]")
    if args.tag:
        path = Path(args.out) / f"episodes_{args.tag}.jsonl"
        regraded = {id(r): (ok, d) for r, ok, d in graded}
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                new = dict(r, ok_stored=r["ok"], oracle_detail_stored=r.get("oracle_detail", ""))
                if id(r) in regraded:
                    ok, d = regraded[id(r)]
                    new.update(ok=bool(ok), oracle_detail=d)
                fh.write(json.dumps(new, ensure_ascii=False) + "\n")
        print(f"wrote {path}")
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

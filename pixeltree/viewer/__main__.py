"""Command line: python -m pixeltree.viewer build | export | snapshot"""

from __future__ import annotations

import argparse
import sys


def cmd_build(a, ap) -> int:
    if a.traces:
        if a.config or a.archive_root:
            ap.error("--traces cannot be combined with --config / --archive-root")
        from .build import run_build_traces
        run_build_traces(a.traces, a.out, a.report, a.jobs)
    else:
        if not (a.config and a.archive_root):
            ap.error("give either --traces DIR, or both --config and --archive-root")
        from .build import run_build
        run_build(a.config, a.archive_root, a.out, a.report, a.only, a.jobs)
    return 0


def cmd_export(a, ap) -> int:
    from .export import run_export
    run_export(a.archive_root, a.ids, a.out, a.config, a.quality)
    return 0


def cmd_snapshot(a, ap) -> int:
    from .snapshot import snapshot
    n = snapshot(a.site, a.out, a.pages)
    return 1 if n else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pixeltree.viewer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the offline static replay site")
    b.add_argument("--traces", help="directory whose subdirectories are pixeltree.trace/1 episodes")
    b.add_argument("--config", help="runs config for reading a raw archive (with --archive-root)")
    b.add_argument("--archive-root", help="root of the raw archive (with --config)")
    b.add_argument("--out", required=True, help="output directory of the site")
    b.add_argument("--report", help="optional Markdown report to render as report.html")
    b.add_argument("--only", help="raw-archive mode only: build just the episodes whose id starts with this (for debugging)")
    b.add_argument("--jobs", type=int, default=8)
    b.set_defaults(fn=cmd_build)

    e = sub.add_parser("export", help="convert episodes of a raw archive into self-contained trace directories")
    e.add_argument("--archive-root", required=True)
    e.add_argument("--ids", required=True, help="text file with one raw episode id per line")
    e.add_argument("--out", required=True, help="output directory; one subdirectory per episode")
    e.add_argument("--config", help="optional runs config (same format as for build); default: the built-in archive layout")
    e.add_argument("--quality", type=int, default=80, help="WebP quality of the exported images (default 80)")
    e.set_defaults(fn=cmd_export)

    n = sub.add_parser("snapshot", help="headless screenshots of site pages, failing on console errors")
    n.add_argument("--site", required=True)
    n.add_argument("--out", required=True)
    n.add_argument("--pages", nargs="+", required=True)
    n.set_defaults(fn=cmd_snapshot)

    a = ap.parse_args(argv)
    return a.fn(a, ap)


if __name__ == "__main__":
    sys.exit(main())

"""
Run the whole pipeline in order.

WHY THIS EXISTS: eight commands run in sequence is eight chances to run one out
of order, or to forget that changing a definition means rebuilding the model
before the analysis means anything. One command removes that.

It also makes the project a single claim rather than eight: "this runs end to
end from an immutable snapshot and every test passes" is a sentence you can put
in a README and a reviewer can check in one line.

Steps stop on failure by design. A model whose tests fail must not have an
analysis built on top of it.

Usage:
    python -m src.run_all                 full pipeline, fresh pull
    python -m src.run_all --no-ingest     reuse the existing snapshot
    python -m src.run_all --from model    resume from a step
"""

from __future__ import annotations

import argparse
import time

STEPS: list[tuple[str, str, str]] = [
    ("ingest",   "src.ingest",   "Pull a snapshot and write its manifest"),
    ("validate", "src.validate", "Run the integrity checks"),
    ("metrics",  "src.metrics",  "Apply definitions and reconcile the population"),
    ("model",    "src.model",    "Build and test the star schema"),
    ("analysis", "src.analysis", "Run the analysis queries"),
    ("charts",   "src.charts",   "Render the figures"),
    ("export",   "src.export",   "Export aggregates"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ingest", action="store_true",
                        help="skip the pull and use the latest existing snapshot")
    parser.add_argument("--from", dest="start", choices=[s[0] for s in STEPS],
                        help="resume from this step")
    args = parser.parse_args()

    steps = list(STEPS)
    if args.no_ingest:
        steps = [s for s in steps if s[0] != "ingest"]
    if args.start:
        names = [s[0] for s in steps]
        if args.start in names:
            steps = steps[names.index(args.start):]

    import importlib
    started = time.time()

    for i, (name, module, description) in enumerate(steps, start=1):
        print("\n" + "=" * 72)
        print(f"STEP {i}/{len(steps)}  {name}  |  {description}")
        print("=" * 72)
        t0 = time.time()
        mod = importlib.import_module(module)
        # Modules built early in the project expose main(); later ones expose
        # run(). Resolve whichever is there rather than renaming working code
        # and risking a change nobody asked for.
        entry = getattr(mod, "run", None) or getattr(mod, "main", None)
        if entry is None:
            raise SystemExit(f"{module} exposes neither run() nor main()")
        try:
            entry()
        except SystemExit as exc:
            # A step that raises SystemExit failed a check on purpose. Stopping
            # here is the point: nothing downstream should be built on it.
            print(f"\n  STOPPED at '{name}': {exc}")
            raise
        print(f"\n  {name} finished in {time.time() - t0:,.1f}s")

    print("\n" + "=" * 72)
    print(f"Pipeline complete in {time.time() - started:,.1f}s")
    print("  Decision memo : reports/recommendation_memo.md")
    print("  Figures       : reports/charts/")
    print("=" * 72)


if __name__ == "__main__":
    main()

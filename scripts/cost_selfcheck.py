"""Software fixtures for run_cost; no Java process or research measurement."""
from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path
import re
import sys
import types

import build
import run_cost
from _common import atomic_json, load_helpers, new_output, stamp


def function_node(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["output", "src", "original-androlic-builder", "original-measured-runner", "build-dir", "probe-build", "deps", "jdk8", "helpers"]:
        p.add_argument("--" + name, required=True)
    args = p.parse_args(argv)
    output = new_output(args.output)
    checks = []
    original = function_node(args.original_androlic_builder, "transform")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[original], type_ignores=[]), "original_Androlic_transform", "exec"), namespace)
    source = (Path(args.src) / "rev8/Androlic8.java").read_text(encoding="utf-8")
    assert build.measured_androlic(source) == namespace["transform"](source)
    checks.append("Androlic measured source byte-identical to original reviewed transform")
    assert ast.dump(function_node(args.original_measured_runner, "read_androlic_gc_metrics"), include_attributes=False) == ast.dump(
        function_node(Path(__file__).with_name("cost_validation.py"), "read_androlic_gc_metrics"), include_attributes=False)
    checks.append("GC validation function structurally identical to original pure reader")
    jobs = run_cost.schedule()
    assert jobs == run_cost.schedule() and len(jobs) == len(set(jobs)) == 25
    assert set(jobs) == {(config, rep) for config in run_cost.CONFIGS for rep in range(1, 6)}
    checks.append("deterministic seed20260930 schedule contains all five configurations x five repetitions")

    legacy, _ = load_helpers(args.helpers, "run_static", "gc_artifact_validation")
    import cost_validation as reader
    apk = output / "software_fixture.apk"
    apk.write_bytes(b"software fixture only; not an APK or measurement input")
    platform = output / "fixture_platforms/android-29"
    platform.mkdir(parents=True)
    (platform / "android.jar").write_bytes(b"software fixture")
    active, maximum = 0, 0

    def process(command, *, cwd, record_path, log_path, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            folder = Path(cwd)
            index = int(folder.name.split("_", 1)[0])
            if index == 4:
                raise OSError("fixture process launch failure")
            resource = {"status": "timeout" if index == 1 else "ok", "exit_code": 124 if index == 1 else 0,
                        "started_at": stamp(), "ended_at": stamp(), "wall_seconds": .01,
                        "peak_root_working_set_bytes": None, "peak_tree_sampled_working_set_bytes": None,
                        "sample_interval_s": .5, "memory_missing_reason": "fixture; no process exists",
                        "metadata": {"fixture_only": True}}
            atomic_json(record_path, resource)
            Path(log_path).write_text("SOFTWARE FIXTURE; NO JAVA OR APK RUN\n", encoding="utf-8")
            lc, policy, _, _, label, rep = command[command.index("rev8.Androlic8Measured") + 1:]
            with (folder / "java.run.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(legacy.ANDRO_COLS)
                writer.writerow([label, lc, policy, rep, 1, 1, 0, 0, 2, ".01", 1, 1, 1, 7, "OK"])
            with (folder / "java.run.components.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(legacy.COMP_COLS)
                writer.writerow([label, lc, policy, rep, "FixtureActivity", "ACT", "SOLVEFAIL:Fixture" if index == 2 else "OK", 7, 2, ".01"])
            for path in reader.gc_paths(folder):
                path.write_text("fixture; real GC reader tested separately by source identity\n", encoding="utf-8")
            return resource
        finally:
            active -= 1

    def gc_metrics(folder, label, config, rep):
        if int(Path(folder).name.split("_", 1)[0]) == 3:
            raise ValueError("fixture malformed GC sidecar")
        return {"androlic_status": "OK", "generation_solve_complete": True,
                "original_generation_solve_seconds": .01, "legacy_reported_live_any_mb": 1,
                "legacy_reported_live_major_mb": 1, "legacy_reported_major_gcs": 1,
                "forced_gc_after_heap_bytes": None, "forced_gc_missing_reason": "fixture deliberately missing"}

    original_loader, original_gc = run_cost.load_helpers, reader.read_androlic_gc_metrics
    run_cost.load_helpers = lambda *names: (types.SimpleNamespace(run_command=process), legacy, None)
    reader.read_androlic_gc_metrics = gc_metrics
    campaign = output / "fixture_campaign"
    try:
        status = run_cost.main(["--apk", str(apk), "--platforms", str(platform.parent), "--jdk8", args.jdk8,
                                "--deps", args.deps, "--build-dir", args.build_dir, "--probe-build", args.probe_build,
                                "--helpers", args.helpers, "--output", str(campaign)])
    finally:
        run_cost.load_helpers = original_loader
        reader.read_androlic_gc_metrics = original_gc
    state = json.loads((campaign / "state.json").read_text(encoding="utf-8"))
    assert status == 1 and state["status"] == "finished_with_failures" and state["processed"] == 25
    assert [r["status"] for r in state["results"][:4]] == ["timeout", "invalid_output", "invalid_output", "launch_or_setup_error"]
    assert sum(r["status"] == "ok" for r in state["results"]) == 21
    assert maximum == 1
    assert all((Path(r["folder"]) / "resource.json").is_file() and r["ended_at"] for r in state["results"])
    summary = json.loads((campaign / "summary.json").read_text(encoding="utf-8"))
    assert all(row["medians"]["forced_gc_after_heap_bytes"] is None for row in summary["configurations"])
    assert any(row["eligible_five_repeat_median"] for row in summary["configurations"])
    assert any(not row["eligible_five_repeat_median"] for row in summary["configurations"])
    checks.append("serial fixture schedule persists timeout, SOLVEFAIL, malformed GC and launch failures")
    checks.append("only five successful repetitions yield medians; missing GC data stays null")
    result = {"fixture_only": True, "Java_or_APK_runs": 0, "status": "ok", "checks": checks,
              "fixture_instances": 25, "maximum_fixture_process_concurrency": maximum}
    atomic_json(output / "selfcheck.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

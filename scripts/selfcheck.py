"""Light fixture checks for the portable scripts; never run Java/APK analyses.

All fake process/CSV values are isolated under the new --output test directory
and labelled as fixtures. They are software tests, not experimental evidence.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import types

import build
import build_fragbench
import run_export
from _common import atomic_json, new_output, stamp


def expect_error(function):
    try:
        function()
    except (ValueError, OSError):
        return
    raise AssertionError("expected rejection")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--src", required=True)
    p.add_argument("--original-probe-builder", required=True)
    p.add_argument("--build-dir", required=True, help="actual isolated Gen8 compilation from build.py")
    p.add_argument("--deps", required=True)
    p.add_argument("--jdk8", required=True)
    p.add_argument("--helpers", required=True)
    args = p.parse_args(argv)
    output = new_output(args.output)
    checks = []
    source = (Path(args.src) / "rev8/DumpGen8.java").read_text(encoding="utf-8")
    original = ast.parse(Path(args.original_probe_builder).read_text(encoding="utf-8"))
    function = next(node for node in original.body if isinstance(node, ast.FunctionDef) and node.name == "transform")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "original_probe_transform", "exec"), namespace)
    assert build.measured_gen8(source) == namespace["transform"](source, "gen8")
    checks.append("measured exporter source is byte-identical to original reviewed transform")
    expect_error(lambda: build.measured_gen8("class Broken {}"))
    checks.append("changed source layout rejected instead of guessed")

    occupied = output / "occupied"
    occupied.mkdir()
    (occupied / "old.txt").write_text("fixture", encoding="utf-8")
    expect_error(lambda: new_output(occupied))
    expect_error(lambda: new_output(occupied / "child", inputs=[occupied]))
    checks.append("nonempty and input-overlapping outputs refused")

    project = output / "fixture_project"
    project.mkdir()
    (project / "cases.csv").write_text("id,expect\na1,leak\na2,noleak\n", encoding="utf-8")
    assert build_fragbench.case_ids(project / "cases.csv", 2) == ["a1", "a2"]
    expect_error(lambda: build_fragbench.case_ids(project / "cases.csv", 36))
    # An arbitrary stale APK outside each exact Gradle output is insufficient.
    (project / "old.apk").write_bytes(b"software fixture; never an analysed APK")
    expect_error(lambda: build_fragbench.collect_apks(project, ["a1", "a2"]))
    for cid in ["a1", "a2"]:
        folder = project / cid / "build/outputs/apk/debug"
        folder.mkdir(parents=True)
        (folder / (cid + ".apk")).write_bytes(b"software fixture")
    assert len(build_fragbench.collect_apks(project, ["a1", "a2"])) == 2
    (project / "a1/build/outputs/apk/debug/duplicate.apk").write_bytes(b"software fixture")
    expect_error(lambda: build_fragbench.collect_apks(project, ["a1", "a2"]))
    checks.append("missing, wrong-count and duplicate APK collections refused")

    apk = output / "fixture_input.apk"
    apk.write_bytes(b"not a real APK; no Java invocation is made by this test")
    platforms = output / "fixture_platforms/android-29"
    platforms.mkdir(parents=True)
    (platforms / "android.jar").write_bytes(b"not an Android platform; software fixture")
    original_loader = run_export.load_helpers
    for scenario in ["timeout", "failed", "invalid_output", "ok"]:
        def run_command(command, *, cwd, record_path, log_path, **kwargs):
            resource = {"status": scenario if scenario in {"timeout", "failed"} else "ok",
                        "exit_code": 124 if scenario == "timeout" else 1 if scenario == "failed" else 0,
                        "started_at": stamp(), "ended_at": stamp(), "wall_seconds": .01,
                        "peak_root_working_set_bytes": None, "peak_tree_sampled_working_set_bytes": None,
                        "sample_interval_s": .5, "memory_missing_reason": "fixture process; no JVM launched",
                        "metadata": {"fixture_only": True}}
            atomic_json(record_path, resource)
            Path(log_path).write_text("SOFTWARE FIXTURE: NO ANALYZER RUN\n", encoding="utf-8")
            return resource

        def validate_export(*values):
            if scenario == "invalid_output":
                raise ValueError("fixture truncated CSV")
            return {"outputs": [], "internal_generation_seconds": .001,
                    "summary": ["fixture", "gen8-fixed_perarg", "OK", "1", "1", "0", "7", ".001", "0"]}

        run_export.load_helpers = lambda *values: (types.SimpleNamespace(run_command=run_command),
                                                   types.SimpleNamespace(validate_export=validate_export))
        target = output / ("fixture_run_export_" + scenario)
        try:
            exit_code = run_export.main(["--apk", str(apk), "--platforms", str(platforms.parent),
                                         "--lifecycle", "fixed", "--policy", "perarg", "--output", str(target),
                                         "--label", "software_fixture", "--jdk8", args.jdk8, "--deps", args.deps,
                                         "--build-dir", args.build_dir, "--helpers", args.helpers])
        finally:
            run_export.load_helpers = original_loader
        receipt = json.loads((target / "result.json").read_text(encoding="utf-8"))
        assert receipt["status"] == scenario
        assert exit_code == (0 if scenario == "ok" else 1)
        assert (target / "resource.json").is_file() and receipt["ended_at"]
        assert receipt["formal_performance"] is False
    checks.append("success, validation failure, process failure and timeout persist terminal receipts/resources")
    report = {"fixture_only": True, "Java_or_APK_runs": 0, "status": "ok", "checks": checks}
    atomic_json(output / "selfcheck.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

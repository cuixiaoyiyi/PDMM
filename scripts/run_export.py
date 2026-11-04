"""Export one real APK through Gen8, with external resources and strict validation.

This is a functional single-APK entry point, not the paper's controlled-background
500-run performance protocol. It never treats an existing CSV as completed work.
Original helpers: resource_monitor.py, run_exports.py, run_static.py; measured mode
also needs run_exports_measured.py and gc_artifact_validation.py. Python: psutil.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import sys

from _common import (atomic_json, class_records, clean_success, dependency,
                     file_record, jdk_tool, load_helpers, new_output,
                     require_dir, require_file, stamp)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apk", required=True)
    p.add_argument("--platforms", required=True, help="Android platforms root consumed by Soot")
    p.add_argument("--lifecycle", choices=["fixed", "hsm"], required=True)
    p.add_argument("--policy", choices=["perarg", "pertype", "rules"], required=True)
    p.add_argument("--output", required=True, help="new or empty output directory")
    p.add_argument("--label", required=True, help="safe CSV/file label; no path separators")
    p.add_argument("--jdk8", required=True)
    p.add_argument("--deps", required=True)
    p.add_argument("--build-dir", required=True, help="compiled Gen8 class directory, e.g. BUILD/gen8")
    p.add_argument("--helpers", required=True)
    p.add_argument("--probe-build", help="BUILD/gen8-probe; enables the real GC-measured exporter")
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--sample-interval", type=float, default=0.5)
    p.add_argument("--xmx", default="8g")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", args.label):
        raise ValueError("label must be a safe, nonempty filename/CSV identifier")
    if not re.fullmatch(r"[1-9][0-9]*[kKmMgG]", args.xmx):
        raise ValueError("invalid --xmx")
    if not all(math.isfinite(x) and x > 0 for x in [args.timeout, args.sample_interval]):
        raise ValueError("timeout and sample interval must be finite and positive")
    apk = require_file(args.apk, "APK")
    platforms = require_dir(args.platforms, "Android platforms")
    if not any(platforms.rglob("android.jar")):
        raise ValueError("platforms directory contains no android.jar")
    build = require_dir(args.build_dir, "compiled Gen8")
    require_file(build / "rev8/DumpGen8.class", "Gen8 exporter class")
    require_file(build / "rev8/Gen8.class", "Gen8 implementation class")
    java = jdk_tool(args.jdk8, "java")
    jar = dependency(args.deps, "DMMPP.jar")
    helpers = require_dir(args.helpers, "original helpers")
    probe = require_dir(args.probe_build, "measured exporter") if args.probe_build else None
    if probe:
        require_file(probe / "rev8/DumpGen8Measured.class", "measured exporter class")
        require_file(probe / "rev/measure/ExportGcProbe.class", "GC probe class")
    root = new_output(args.output, inputs=[apk, platforms, build, jar, helpers / "run_exports.py"] + ([probe] if probe else []))
    config = args.lifecycle + "/" + args.policy
    receipt = {"schema_version": 1, "kind": "gen8", "label": args.label, "config": config,
               "status": "running", "started_at": stamp(), "output": str(root),
               "measurement_scope": "functional single-APK export; external process wall/resources",
               "formal_performance": False, "time_load_affected": True,
               "exclusive_background_enforced": False, "original_outputs_preserved": True}
    atomic_json(root / "result.json", receipt)
    try:
        monitor, exports = load_helpers(helpers, "resource_monitor", "run_exports")
        names = ["resource_monitor.py", "run_exports.py", "run_static.py"]
        measured = None
        if probe:
            measured, = load_helpers(helpers, "run_exports_measured")
            names += ["run_exports_measured.py", "gc_artifact_validation.py"]
        classpath = ([probe] if probe else []) + [build, jar]
        main_class = "rev8.DumpGen8Measured" if probe else "rev8.DumpGen8"
        command = [str(java), "-Duser.language=en", "-Duser.country=US", "-Xmx" + args.xmx,
                   "-cp", os.pathsep.join(map(str, classpath)), main_class,
                   str(platforms), str(apk), str(root), args.label, args.lifecycle, args.policy]
        atomic_json(root / "inputs.json", {"schema_version": 1, "arguments": vars(args), "apk": file_record(apk),
                                           "java": file_record(java), "jars": [file_record(jar)],
                                           "classes": class_records(build), "probe_classes": class_records(probe) if probe else [],
                                           "platforms": [file_record(p) for p in sorted(platforms.rglob("android.jar"))],
                                           "helpers": [file_record(helpers / name) for name in names], "command": command})
        resource = monitor.run_command(command, cwd=str(root), log_path=str(root / "process.log"),
                                       record_path=str(root / "resource.json"), timeout_s=args.timeout,
                                       metadata={"kind": "gen8", "mode": "functional", "label": args.label,
                                                 "config": config, "concurrency_at_start": 1, "max_observed_concurrency": 1,
                                                 "requested_parallelism": 1, "time_load_affected": True},
                                       sample_interval_s=args.sample_interval)
        receipt.update(resource_record=str(root / "resource.json"), exit_code=resource.get("exit_code"),
                       external_wall_seconds=resource.get("wall_seconds"),
                       peak_root_working_set_bytes=resource.get("peak_root_working_set_bytes"),
                       peak_tree_sampled_working_set_bytes=resource.get("peak_tree_sampled_working_set_bytes"),
                       sample_interval_s=resource.get("sample_interval_s"),
                       memory_missing_reason=resource.get("memory_missing_reason"))
        if not clean_success(resource):
            receipt["status"] = "failed" if resource.get("cleanup_error") else resource.get("status", "failed")
            if resource.get("cleanup_error"):
                receipt["cleanup_error"] = resource["cleanup_error"]
            return 1
        receipt["status"] = "invalid_output"
        validated = exports.validate_export("gen8", root, args.label, config)
        if measured:
            metrics, events = measured.metric_paths("gen8", root, args.label, config)
            gc = measured.read_gc_metrics(metrics, events)
            if gc["export_status"] != "OK" or not gc["generation_complete"]:
                raise ValueError("GC probe reports incomplete generation")
            if abs(gc["original_generation_seconds"] - validated["internal_generation_seconds"]) > .011:
                raise ValueError("GC stage time differs from the exporter summary")
            validated["outputs"] += [file_record(metrics), file_record(events)]
            receipt["gc_metrics"] = gc
        receipt.update(status="ok", outputs=validated["outputs"],
                       internal_generation_seconds=validated["internal_generation_seconds"],
                       formal_slots=int(validated["summary"][6]), generated_components=int(validated["summary"][4]))
        print(f"Validated {args.label} {config}: {receipt['formal_slots']} data-formal slots")
        return 0
    except Exception as error:
        if receipt["status"] == "running":
            receipt["status"] = "launch_or_setup_error"
        receipt["error"] = f"{type(error).__name__}: {error}"
        print(receipt["error"], file=sys.stderr)
        return 1
    finally:
        receipt["ended_at"] = stamp()
        atomic_json(root / "result.json", receipt)


if __name__ == "__main__":
    raise SystemExit(main())

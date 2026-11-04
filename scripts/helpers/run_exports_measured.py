#!/usr/bin/env python3
"""Independent export entry point using isolated measured exporter classes.

All ordinary run_exports arguments remain supported; --probe-build is required.
The underlying runner module is adapted only within this new Python process;
its source files and all frozen active runners remain untouched.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

import run_exports as base
from resource_monitor import run_command
from run_static import atomic_csv, atomic_json, sha256
from gc_artifact_validation import validate_gc_core

HERE = Path(__file__).resolve().parent
GC_COLUMNS = ["generation_peak_after_any_gc_bytes", "generation_peak_after_major_gc_bytes", "generation_gc_notification_count",
    "generation_major_gc_notification_count", "forced_gc_after_heap_bytes", "forced_major_gc_notification_confirmed",
    "forced_gc_total_overhead_seconds", "forced_gc_missing_reason", "generation_major_gc_missing_reason", "gc_metrics_record"]

def metric_paths(kind, attempt, label, config):
    stem = label + "." + config.replace("/", "_") if kind == "gen8" else label
    return Path(attempt) / (stem + ".gc.metrics.json"), Path(attempt) / (stem + ".gc.events.csv")

def read_gc_metrics(metric, events):
    raw = metric.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("truncated GC JSON")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("GC metrics must be a JSON object")
    required = {"schema_version", "export_status", "generation_complete", "original_generation_seconds", "registered_collectors",
        "generation_gc_window", "before_forced_gc_ids", "listener_attach_uptime_ms", "listener_detach_uptime_ms", "notification_count",
        "event_rows_dropped", "forced_gc_requested", "forced_major_gc_notification_confirmed", "forced_gc_after_heap_bytes",
        "forced_gc_total_overhead_seconds", "forced_gc_missing_reason", "generation_any_gc_missing_reason", "generation_major_gc_missing_reason"}
    if not required <= set(data) or data["schema_version"] != 1:
        raise ValueError("incomplete / wrong GC measurement schema")
    raw_events = events.read_bytes()
    if not raw_events.endswith(b"\n"):
        raise ValueError("truncated GC events CSV")
    with events.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, strict=True)
        expected_columns = ["ordinal", "collector", "cause", "action", "gc_id", "start_uptime_ms", "end_uptime_ms", "duration_ms",
                            "heap_used_after_gc_bytes", "major_action", "in_generation_window", "matches_probe_gc_request"]
        if reader.fieldnames != expected_columns:
            raise ValueError("GC event CSV header is missing / invalid")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("GC event row is malformed")
    validate_gc_core(data, rows, "generation")
    if data["original_generation_seconds"] is None or not math.isfinite(data["original_generation_seconds"]):
        raise ValueError("original generation duration is missing")
    for key in ("notification_count", "event_rows_dropped", "generation_gc_notification_count", "generation_major_gc_notification_count"):
        if not isinstance(data.get(key), int) or data[key] < 0:
            raise ValueError("invalid GC event count: " + key)
    if not isinstance(data["forced_gc_total_overhead_seconds"], (int, float)) or not math.isfinite(data["forced_gc_total_overhead_seconds"]) or data["forced_gc_total_overhead_seconds"] < 0:
        raise ValueError("forced GC overhead is not measured")
    for field, reason in (("generation_peak_after_any_gc_bytes", "generation_any_gc_missing_reason"),
                          ("generation_peak_after_major_gc_bytes", "generation_major_gc_missing_reason"),
                          ("forced_gc_after_heap_bytes", "forced_gc_missing_reason")):
        if data.get(field) is None:
            if not data.get(reason):
                raise ValueError("unexplained missing GC metric: " + field)
        elif not isinstance(data[field], (int, float)) or data[field] < 0:
            raise ValueError("invalid GC heap occupancy")
    if data["forced_major_gc_notification_confirmed"]:
        if data["forced_gc_after_heap_bytes"] is None:
            raise ValueError("GC confirmed without corresponding after-GC occupancy")
        if not data["event_rows_dropped"] and not any(r["matches_probe_gc_request"] == "true" and r["major_action"] == "true" for r in rows):
            raise ValueError("forced major confirmation lacks recorded event")
    elif data["forced_gc_after_heap_bytes"] is not None:
        raise ValueError("unconfirmed request cannot be labelled after-GC live heap")
    return validate_gc_core(data, rows, "generation")

def main(argv=None, monitor=run_command):
    args = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--probe-build", required=True)
    own, forwarded = p.parse_known_args(args)
    if not forwarded or forwarded[0] not in {"gen8", "fd"}:
        raise ValueError("expected gen8 or fd export kind")
    kind = forwarded[0]
    build = Path(own.probe_build).resolve()
    main_class = "rev8.DumpGen8Measured" if kind == "gen8" else "rev.DumpFlowDroidDMMMeasured"
    if not (build / "rev/measure/ExportGcProbe.class").is_file() or not (build / (main_class.replace(".", "/") + ".class")).is_file():
        raise ValueError("isolated measured exporter / GC probe classes missing")
    originals = {name: getattr(base, name) for name in ("command_for", "validate_export", "tree_manifest", "run_one", "publish")}
    expected_legacy_build = "build8" if kind == "gen8" else "build17"

    def command_for(job, batch, attempt):
        command = originals["command_for"](job, batch, attempt)
        cp_index = command.index("-cp") + 1
        pieces = command[cp_index].split(";")
        # FD retains JAR first; Gen8 retains generator build before the legacy JAR.
        pieces.insert(0 if kind == "gen8" else 1, str(build))
        command[cp_index] = ";".join(pieces)
        command[command.index("rev8.DumpGen8" if kind == "gen8" else "rev.DumpFlowDroidDMM")] = main_class
        return command

    def tree_manifest(path, pattern):
        rows = originals["tree_manifest"](path, pattern)
        if Path(path).name == expected_legacy_build:
            rows += originals["tree_manifest"](build, "*.class")
            sources = [Path(__file__), HERE / "gc_artifact_validation.py", HERE / "instrumentation/rev/measure/ExportGcProbe.java", HERE / "instrumentation/build_export_probes.py"]
            rows += [{"path": str(source.resolve()), "size": source.stat().st_size, "sha256": sha256(source)} for source in sources]
        return rows

    def validate_export(k, attempt, label, config):
        validated = originals["validate_export"](k, attempt, label, config)
        metric, events = metric_paths(k, attempt, label, config)
        data = read_gc_metrics(metric, events)
        if data["export_status"] != "OK" or not data["generation_complete"]:
            raise ValueError("GC measurement corresponds to failed / incomplete generation")
        if abs(data["original_generation_seconds"] - validated["internal_generation_seconds"]) > .011:
            raise ValueError("GC record and original summary generation duration disagree")
        validated["outputs"] += [{"path": str(path), "size": path.stat().st_size, "sha256": sha256(path)} for path in (metric, events)]
        validated["gc_metrics"] = data
        return validated

    def run_one(job, batch, process_monitor=monitor, observe=None):
        result = originals["run_one"](job, batch, process_monitor, observe)
        metric, events = metric_paths(batch["kind"], result["attempt"], job["label"], job["config"])
        try:
            data = read_gc_metrics(metric, events)
            result.update({key: data.get(key) for key in GC_COLUMNS if key != "gc_metrics_record"})
            result["gc_measurement_quality"] = data["measurement_quality"]
            result["internal_gc_live_heap"] = "GC event observation; natural generation maxima and confirmed final request are separate"
            result["gc_metrics_record"] = str(metric)
        except (OSError, ValueError, KeyError, csv.Error) as exc:
            result.update({key: None for key in GC_COLUMNS})
            result["internal_gc_live_heap"] = "missing: " + str(exc)
            result["gc_measurement_quality"] = "missing or invalid; exporter failed, timed out, or instrumentation incomplete"
        atomic_json(Path(result["attempt"]) / "result.json", {key: value for key, value in result.items() if key != "reused"})
        return result

    def publish(root, state):
        originals["publish"](root, state)
        columns = ["dataset", "label", "config", "status", "internal_generation_seconds", "external_wall_seconds"] + GC_COLUMNS + ["gc_measurement_quality"]
        atomic_csv(root / "gc_measurements.csv", [columns] + [[row.get(column) for column in columns] for _, row in sorted(state["instances"].items())])

    try:
        base.command_for, base.validate_export, base.tree_manifest, base.run_one, base.publish = command_for, validate_export, tree_manifest, run_one, publish
        return base.main(forwarded, monitor)
    finally:
        for name, function in originals.items():
            setattr(base, name, function)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("measured export runner: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

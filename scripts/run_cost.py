"""Serial measured Androlic runs for one APK with explicit input and output paths.

Defaults: five configurations x five repetitions, order seed 20260930, 12GiB heap,
1800s per process, 500 paths/component, 0.5s external resource sampling.
This launches a NEW reproducible measurement on the caller's environment. It
does not reproduce or assert equivalence to the historical controlled-background
500-run campaign. Each instance uses a separate output directory and monitors its own child processes.
Original helpers: resource_monitor.py, run_static.py, gc_artifact_validation.py.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time

from _common import (atomic_json, class_records, clean_success, dependency,
                     file_record, jdk_tool, load_helpers, new_output,
                     require_dir, require_file, stamp)


CONFIGS = ["fixed/perarg", "fixed/pertype", "fixed/rules", "hsm/perarg", "hsm/rules"]
REPETITIONS, SEED, TIMEOUT, PATHS, SAMPLE = 5, 20260930, 1800, 500, 0.5


def schedule():
    jobs = [(config, rep) for config in CONFIGS for rep in range(1, REPETITIONS + 1)]
    random.Random(SEED).shuffle(jobs)
    return jobs


def validate_cost(legacy, gc_reader, folder, label, config, rep):
    """Use strict component and complete-GC validation, without policy imports."""
    valid = legacy.validate_outputs("androlic", folder, label, config, rep)
    row, components = valid["run_row"], valid["detail_rows"]
    if sum(int(r[7]) for r in components) != int(row[13]):
        raise ValueError("component and aggregate formal counts disagree")
    if sum(r[6] == "OK" for r in components) != int(row[5]):
        raise ValueError("generated component count disagrees")
    if any(r[6] == "SPLICED" and (int(r[7]) or int(r[8])) for r in components):
        raise ValueError("spliced component has standalone metrics")
    gc = gc_reader.read_androlic_gc_metrics(folder, label, config, rep)
    if gc["androlic_status"] != "OK" or not gc["generation_solve_complete"]:
        raise ValueError("GC sidecar records incomplete generation or solve")
    if abs(gc["original_generation_solve_seconds"] - float(row[9])) > .011:
        raise ValueError("GC sidecar stage time and Java CSV disagree")
    reported = [gc["legacy_reported_live_any_mb"], gc["legacy_reported_live_major_mb"], gc["legacy_reported_major_gcs"]]
    if reported != [int(value) for value in row[10:13]]:
        raise ValueError("preserved legacy heap metrics disagree with CSV")
    valid["files"] += [file_record(path) for path in gc_reader.gc_paths(folder)]
    valid["gc_metrics"] = gc
    return valid


def summarize(results):
    metrics = ["external_wall_seconds", "java_analysis_seconds", "formals", "symbolic_paths",
               "peak_root_working_set_bytes", "peak_tree_sampled_working_set_bytes", "forced_gc_after_heap_bytes"]
    summaries = []
    for config in CONFIGS:
        rows = [r for r in results if r["config"] == config]
        good = [r for r in rows if r["status"] == "ok"]
        item = {"config": config, "expected_repetitions": REPETITIONS, "recorded": len(rows),
                "successful": len(good), "eligible_five_repeat_median": len(good) == REPETITIONS,
                "medians": {}, "missing_reasons": {}}
        for metric in metrics:
            if len(good) != REPETITIONS:
                item["medians"][metric] = None
                item["missing_reasons"][metric] = "requires all five validated successful repetitions"
            elif any(r.get(metric) is None for r in good):
                item["medians"][metric] = None
                item["missing_reasons"][metric] = "one or more observations explicitly missing"
            else:
                item["medians"][metric] = statistics.median(r[metric] for r in good)
        summaries.append(item)
    return {"scope": "one APK; descriptive medians only; no application-level significance test",
            "measurement_environment": "caller_environment_no_exclusivity_admission",
            "historical_controlled_background_equivalence_claim": False, "configurations": summaries}


def execute(monitor, legacy, gc_reader, *, folder, java, jar, build, probe, apk,
            platforms, label, config, rep):
    folder.mkdir()
    lc, policy = config.split("/")
    cfg = folder / "androlic.cfg"
    cfg.write_text("\n".join([
        "androidPath " + str(platforms), "apkBasePath " + str(apk.parent), "apkName " + apk.name,
        "outputBasePath " + str(folder / "androlic_output"), "javaHome " + str(java.parent.parent),
        "maxRunningTime " + str(TIMEOUT * 1000), "maxPathNumber " + str(PATHS), "maxPathLength 10000",
        "maxContextDepth 4", "maxRecursiveInvocationLevel 3", "maxLoopUnrollNumber 2",
        "debugMode 0", "isJimpleOutput 0", "entryMethod DMMPP", ""]), encoding="utf-8")
    command = [str(java), "-Duser.language=en", "-Duser.country=US", "-Xmx12g", "-cp",
               os.pathsep.join(map(str, [probe, build, jar])), "rev8.Androlic8Measured", lc, policy,
               str(cfg), str(folder / "java.run.csv"), label, str(rep)]
    result = {"schema_version": 1, "label": label, "config": config, "rep": rep,
              "status": "running", "started_at": stamp(), "folder": str(folder),
              "measurement_environment": "caller_environment_no_exclusivity_admission",
              "historical_controlled_background_equivalence_claim": False}
    atomic_json(folder / "inputs.json", {"command": command, "configuration": file_record(cfg),
                                        "protocol": {"xmx": "12g", "timeout": TIMEOUT, "maxpaths": PATHS,
                                                     "sample_interval": SAMPLE, "serial": True},
                                        "shared_inputs": "../../inputs.json"})
    atomic_json(folder / "result.json", result)
    launched = time.perf_counter()
    try:
        resource = monitor.run_command(command, cwd=str(folder), log_path=str(folder / "process.log"),
                                       record_path=str(folder / "resource.json"), timeout_s=TIMEOUT,
                                       metadata={"kind": "androlic", "label": label, "config": config, "repetition": rep,
                                                 "mode": "new_serial_measurement", "concurrency_at_start": 1,
                                                 "max_observed_concurrency": 1, "requested_parallelism": 1,
                                                 "background_exclusivity_enforced": False, "time_load_affected": True},
                                       sample_interval_s=SAMPLE)
        result.update(resource_record=str(folder / "resource.json"), exit_code=resource.get("exit_code"),
                      external_wall_seconds=resource.get("wall_seconds"),
                      peak_root_working_set_bytes=resource.get("peak_root_working_set_bytes"),
                      peak_tree_sampled_working_set_bytes=resource.get("peak_tree_sampled_working_set_bytes"),
                      sample_interval_s=resource.get("sample_interval_s"),
                      memory_missing_reason=resource.get("memory_missing_reason"))
        if not clean_success(resource):
            result["status"] = "failed" if resource.get("cleanup_error") else resource.get("status", "failed")
            if resource.get("cleanup_error"):
                result["cleanup_error"] = resource["cleanup_error"]
            return result
        result["status"] = "invalid_output"
        if not legacy.resource_valid(resource):
            raise ValueError("incomplete external resource record")
        valid = validate_cost(legacy, gc_reader, folder, label, config, rep)
        row, gc = valid["run_row"], valid["gc_metrics"]
        result.update(status="ok", outputs=valid["files"], gc_metrics=gc,
                      java_analysis_seconds=float(row[9]), formals=int(row[13]), symbolic_paths=int(row[8]),
                      forced_gc_after_heap_bytes=gc["forced_gc_after_heap_bytes"],
                      forced_gc_missing_reason=gc.get("forced_gc_missing_reason"))
    except KeyboardInterrupt:
        result["status"] = "interrupted"
        raise
    except Exception as error:
        if result["status"] == "running":
            result["status"] = "launch_or_setup_error"
        result["error"] = f"{type(error).__name__}: {error}"
        if not (folder / "resource.json").exists():
            missing = {"status": "launch_error", "exit_code": None, "started_at": result["started_at"],
                       "ended_at": stamp(), "wall_seconds": time.perf_counter() - launched,
                       "peak_root_working_set_bytes": None, "peak_tree_sampled_working_set_bytes": None,
                       "sample_interval_s": SAMPLE, "memory_missing_reason": "process measurement unavailable: " + result["error"]}
            atomic_json(folder / "resource.json", missing)
            result.update(resource_record=str(folder / "resource.json"), external_wall_seconds=missing["wall_seconds"],
                          memory_missing_reason=missing["memory_missing_reason"])
    finally:
        result["ended_at"] = stamp()
        atomic_json(folder / "result.json", result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for option in ["apk", "platforms", "jdk8", "deps", "build-dir", "probe-build", "helpers", "output"]:
        p.add_argument("--" + option, required=True)
    args = p.parse_args(argv)
    apk, java = require_file(args.apk, "APK"), jdk_tool(args.jdk8, "java")
    platforms, build, probe, helpers = (require_dir(value, name) for value, name in
                                       [(args.platforms, "platforms"), (args.build_dir, "Gen8 classes"),
                                        (args.probe_build, "Androlic probe classes"), (args.helpers, "original helpers")])
    require_file(build / "rev8/Gen8.class", "Gen8 implementation")
    for class_name in ["rev8/Androlic8Measured.class", "rev/measure/AndrolicGcProbe.class", "rev/measure/ExportGcProbe.class"]:
        require_file(probe / class_name, "measured class")
    android_jars = sorted(platforms.rglob("android.jar"))
    if not android_jars:
        raise ValueError("platforms contains no android.jar")
    jar = dependency(args.deps, "Androlic_DMMPP.jar")
    root = new_output(args.output, inputs=[apk, platforms, build, probe, jar, helpers / "run_static.py"])
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", apk.stem).strip("._-")[:150] or "application"
    jobs = schedule()
    state = {"schema_version": 1, "status": "running", "started_at": stamp(), "label": label,
             "expected": len(jobs), "processed": 0, "finished": False, "results": [],
             "protocol": {"configurations": CONFIGS, "repetitions": REPETITIONS, "seed": SEED,
                          "parallelism": 1, "xmx": "12g", "timeout": TIMEOUT, "maxpaths": PATHS, "sample_interval": SAMPLE},
             "schedule": [{"config": config, "rep": rep} for config, rep in jobs],
             "measurement_environment": "caller_environment_no_exclusivity_admission",
             "historical_controlled_background_equivalence_claim": False, "time_load_affected": True}
    atomic_json(root / "state.json", state)
    try:
        monitor, legacy, _ = load_helpers(helpers, "resource_monitor", "run_static", "gc_artifact_validation")
        import cost_validation as gc_reader
        if Path(gc_reader.__file__).resolve() != Path(__file__).with_name("cost_validation.py").resolve():
            raise ValueError("wrong portable GC validator module resolved")
        atomic_json(root / "inputs.json", {"arguments": vars(args), "apk": file_record(apk), "java": file_record(java),
                                           "jar": file_record(jar), "classes": class_records(build),
                                           "probe_classes": class_records(probe),
                                           "platforms": [file_record(a) for a in android_jars],
                                           "helpers": [file_record(helpers / n) for n in ["resource_monitor.py", "run_static.py", "gc_artifact_validation.py"]],
                                           "launcher": file_record(__file__), "gc_validator": file_record(gc_reader.__file__)})
        (root / "instances").mkdir()
        for index, (config, rep) in enumerate(jobs, 1):
            state["current"] = {"index": index, "config": config, "rep": rep}
            atomic_json(root / "state.json", state)
            folder = root / "instances" / f"{index:02d}_{config.replace('/', '_')}_r{rep}"
            result = execute(monitor, legacy, gc_reader, folder=folder, java=java, jar=jar, build=build,
                             probe=probe, apk=apk, platforms=platforms, label=label, config=config, rep=rep)
            state["results"].append(result)
            state["processed"] = len(state["results"])
            atomic_json(root / "state.json", state)
            atomic_json(root / "summary.json", summarize(state["results"]))
            print(f"[{index}/{len(jobs)}] {config} repetition {rep}: {result['status']}", flush=True)
        state.update(status="completed" if all(r["status"] == "ok" for r in state["results"]) else "finished_with_failures",
                     finished=True, successful=sum(r["status"] == "ok" for r in state["results"]))
        return 0 if state["status"] == "completed" else 1
    except KeyboardInterrupt:
        state.update(status="interrupted", finished=False)
        return 130
    except Exception as error:
        state.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(state["error"], file=sys.stderr)
        return 1
    finally:
        state["ended_at"] = stamp()
        atomic_json(root / "state.json", state)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Recoverable generation-evidence exports, with measured per-instance resources.

Gen8: fixed/perarg, fixed/pertype, fixed/rules, hsm/perarg, hsm/pertype,
hsm/rules. These are revised generators, distinct from the original E5 DMMPP.
FD: native only, with the original FlowDroid JAR before build17. Existing E5
FlowDroid baselines are protected against accidental reruns.

These functional exports are load-affected evidence collection. This runner does
not provide a formal performance entry point. Every Java invocation has a
resource.json and an immutable attempt; internal generator seconds stay separate.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import sys
import threading
import time
import uuid

import psutil

from resource_monitor import run_command
from run_static import (AdaptiveSlots, BatchRegistry, FileLock, atomic_csv, atomic_json, csv_rows,
                        digest, native_path, now, numeric, resource_valid, sha256, tree_manifest)

HERE = Path(__file__).resolve().parent
VERSION = 1
GEN8_CONFIGS = ["fixed/perarg", "fixed/pertype", "fixed/rules", "hsm/perarg", "hsm/pertype", "hsm/rules"]

def validate_export(kind, attempt, label, config):
    attempt = Path(attempt)
    if kind == "gen8":
        generator = "gen8-" + config.replace("/", "_")
        stem = label + "." + config.replace("/", "_")
        widths = {"summary.csv": 9, "components.csv": 9, "edges.csv": 6, "args.csv": 8, "merges.csv": 3}
    else:
        generator, stem = "flowdroid-2.15.1", label
        widths = {"summary.csv": 9, "edges.csv": 6, "args.csv": 8}
    paths = {suffix: attempt / (stem + "." + suffix) for suffix in list(widths) + ["jimple"]}
    data = {suffix: csv_rows(paths[suffix], width) for suffix, width in widths.items()}
    if len(data["summary.csv"]) != 1:
        raise ValueError("export summary must contain exactly one complete row")
    summary = data["summary.csv"][0]
    if summary[:3] != [label, generator, "OK"]:
        raise ValueError("Java generation did not fully succeed")
    for i in range(3, 9):
        numeric(summary[i], integer=i != (7 if kind == "gen8" else 8))
    for suffix, rows in data.items():
        if any(row[:2] != [label, generator] for row in rows):
            raise ValueError("export row identity disagrees: " + suffix)
    edges, arguments = data["edges.csv"], data["args.csv"]
    if any(row[5] not in {"0", "1"} or not all(row[2:5]) for row in edges):
        raise ValueError("edge row is incomplete or has invalid allocation flag")
    if len({tuple(row) for row in edges}) != len(edges):
        raise ValueError("duplicate edges")
    for row in arguments:
        numeric(row[4], integer=True)
        if not all(row[2:4] + row[5:8]):
            raise ValueError("argument row has missing fields")
    raw_jimple = paths["jimple"].read_bytes()
    if raw_jimple and not raw_jimple.endswith(b"\n"):
        raise ValueError("Jimple is truncated (missing final newline)")
    jimple = raw_jimple.decode("utf-8-sig")
    markers = [line for line in jimple.splitlines() if line.startswith("// ---- ")]
    if kind == "gen8":
        components = data["components.csv"]
        if len(components) != int(summary[3]) or len({row[2] for row in components}) != len(components):
            raise ValueError("missing / duplicate component rows")
        if int(summary[5]) != 0 or any(row[4] not in {"OK", "SPLICED"} for row in components):
            raise ValueError("one or more components failed despite top-level OK")
        names = {row[2] for row in components}
        for row in components:
            for i in range(5, 9):
                numeric(row[i], integer=True)
            if row[4] == "SPLICED" and any(int(v) for v in row[5:]):
                raise ValueError("spliced component should have zero standalone metrics")
        generated = sum(row[4] == "OK" for row in components)
        spliced = len(components) - generated
        if generated != int(summary[4]) or int(summary[8]) < spliced:
            raise ValueError("generation / hosting count disagrees")
        if sum(int(row[5]) for row in components) != int(summary[6]):
            raise ValueError("formal count disagrees with summary")
        if any(row[2] not in names for row in edges + arguments):
            raise ValueError("edge/argument refers to an absent component")
        for row in components:
            if sum(edge[2] == row[2] for edge in edges) != int(row[8]):
                raise ValueError("per-component edge count disagrees")
        if len(markers) != generated or (generated and not jimple.rstrip().endswith("}")):
            raise ValueError("Jimple missing one or more generated methods")
        if any(not row[2] or row[2].split(",", 1)[0] not in names for row in data["merges.csv"]):
            raise ValueError("merge evidence refers to absent components")
        seconds = float(summary[7])
    else:
        if len(edges) != int(summary[7]):
            raise ValueError("FlowDroid edge count disagrees with summary")
        if "// entry method: " not in jimple or not markers:
            raise ValueError("FlowDroid entry / method bodies missing")
        if not (jimple.rstrip().endswith("}") or jimple.rstrip().endswith("// (no body)")):
            raise ValueError("FlowDroid Jimple has an incomplete final method")
        seconds = float(summary[8])
    outputs = [{"path": str(path), "size": path.stat().st_size, "sha256": sha256(path)} for path in paths.values()]
    return {"summary": summary, "internal_generation_seconds": seconds, "outputs": outputs,
            "edge_rows": len(edges), "argument_rows": len(arguments),
            "component_rows": len(data.get("components.csv", [])), "merge_rows": len(data.get("merges.csv", []))}

def prior_success(job, kind):
    attempts = Path(job["folder"]) / "attempts"
    if not attempts.exists():
        return None
    for folder in sorted(attempts.iterdir(), reverse=True):
        try:
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            resource = json.loads((folder / "resource.json").read_text(encoding="utf-8"))
            inputs = json.loads((folder / "inputs.json").read_text(encoding="utf-8"))
            if result.get("fingerprint") != job["fingerprint"] or result.get("status") != "ok" or not resource_valid(resource):
                continue
            if inputs.get("fingerprint") != job["fingerprint"] or inputs.get("parameters") != job["parameters"]:
                continue
            if resource.get("metadata", {}).get("fingerprint") != job["fingerprint"]:
                continue
            valid = validate_export(kind, folder, job["label"], job["config"])
            if valid["outputs"] != result.get("outputs"):
                continue
            return {**result, "reused": True}
        except (OSError, ValueError, KeyError, csv.Error):
            continue
    return None

def command_for(job, batch, attempt):
    work = Path(batch["work"])
    java = batch["java"]
    common = [java, "-Duser.language=en", "-Duser.country=US", "-Xmx" + batch["xmx"]]
    if batch["kind"] == "gen8":
        lc, pm = job["config"].split("/")
        return common + ["-cp", str(work / "build8") + os.pathsep + str(work / "lib/DMMPP.jar"), "rev8.DumpGen8",
            str(work / "platforms"), job["apk_path"], str(attempt), job["label"], lc, pm]
    # Preserve the original E5 baseline's class resolution order. The patched
    # build17 first order is for revised taint configurations, not this native dump.
    return common + ["-cp", str(work / "lib/flowdroid-2.15.1.jar") + os.pathsep + str(work / "build17"), "rev.DumpFlowDroidDMM",
        str(work / "platforms"), job["apk_path"], str(attempt), job["label"]]

def run_one(job, batch, monitor=run_command, observe=None):
    reused = prior_success(job, batch["kind"])
    if reused:
        return reused
    attempts = Path(job["folder"]) / "attempts"
    attempt = attempts / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "." + uuid.uuid4().hex[:12])
    attempt.mkdir(parents=True)
    atomic_json(attempt / "inputs.json", {"fingerprint": job["fingerprint"], "parameters": job["parameters"]})
    metadata = {"kind": batch["kind"], "experiment": batch["name"], "dataset": job["dataset"], "label": job["label"],
        "config": job["config"], "repetition": 1, "fingerprint": job["fingerprint"], "mode": "functional", "time_load_affected": True,
        "requested_parallelism": batch["parallel"], "concurrency_at_start": 1, "max_observed_concurrency": 1, "batch_id": batch["batch_id"]}
    if observe:
        observe(job["key"], metadata)
    started_at, t0 = now(), time.perf_counter()
    try:
        resource = monitor(command_for(job, batch, attempt), cwd=batch["work"], log_path=str(attempt / "process.log"),
            record_path=str(attempt / "resource.json"), timeout_s=batch["timeout"], metadata=metadata, sample_interval_s=batch["sample_interval"])
    except Exception as exc:
        resource = {"status": "launch_error", "exit_code": None, "started_at": started_at, "ended_at": now(),
            "wall_seconds": time.perf_counter() - t0, "metadata": metadata, "error": repr(exc),
            "peak_root_working_set_bytes": None, "peak_tree_sampled_working_set_bytes": None,
            "sample_interval_s": batch["sample_interval"], "memory_missing_reason": "no completed external process measurement"}
    finally:
        if observe:
            observe(job["key"], None)
    resource["metadata"] = metadata
    atomic_json(attempt / "resource.json", resource)
    status, validation_error, valid = resource.get("status", "failed"), None, None
    if resource_valid(resource):
        try:
            valid = validate_export(batch["kind"], attempt, job["label"], job["config"])
            status = "ok"
        except (OSError, ValueError, csv.Error) as exc:
            status, validation_error = "invalid_output", str(exc)
    result = {"schema_version": VERSION, "kind": batch["kind"], "dataset": job["dataset"], "label": job["label"], "config": job["config"],
        "rep": 1, "fingerprint": job["fingerprint"], "attempt": str(attempt), "status": status, "validation_error": validation_error,
        "outputs": valid["outputs"] if valid else [], "resource_record": str(attempt / "resource.json"),
        "started_at": resource.get("started_at"), "ended_at": resource.get("ended_at"), "external_wall_seconds": resource.get("wall_seconds"),
        "exit_code": resource.get("exit_code"), "peak_root_working_set_bytes": resource.get("peak_root_working_set_bytes"),
        "peak_tree_sampled_working_set_bytes": resource.get("peak_tree_sampled_working_set_bytes"),
        "sample_interval_s": resource.get("sample_interval_s"), "memory_missing_reason": resource.get("memory_missing_reason"),
        "concurrency_at_start": metadata["concurrency_at_start"], "max_observed_concurrency": metadata["max_observed_concurrency"],
        "requested_parallelism": batch["parallel"], "time_load_affected": True, "summary": valid["summary"] if valid else None,
        "internal_generation_seconds": valid["internal_generation_seconds"] if valid else None,
        "internal_gc_live_heap": "missing; these generation exporters do not collect GC live-heap measurements"}
    atomic_json(attempt / "result.json", result)
    return {**result, "reused": False}

def publish(root, state):
    atomic_json(root / "state.json", state)
    columns = ["dataset", "label", "config", "rep", "status", "started_at", "ended_at", "external_wall_seconds", "exit_code",
        "peak_root_working_set_bytes", "peak_tree_sampled_working_set_bytes", "sample_interval_s", "memory_missing_reason",
        "concurrency_at_start", "max_observed_concurrency", "requested_parallelism", "time_load_affected", "internal_generation_seconds", "attempt", "resource_record"]
    atomic_csv(root / "instances.csv", [columns] + [[r.get(c, "") for c in columns] for _, r in sorted(state["instances"].items())])
    atomic_json(root / "successful_exports.json", {"finished": state["finished"], "complete_success": state["complete_success"],
        "exports": [r for _, r in sorted(state["instances"].items()) if r["status"] == "ok"]})

def run_batch(batch, jobs, monitor=run_command):
    root = Path(batch["root"])
    state = {"schema_version": VERSION, "kind": batch["kind"], "name": batch["name"], "status": "running", "finished": False,
        "complete_success": False, "started_at": now(), "expected": len(jobs), "processed": 0, "ok": 0, "failed": 0,
        "instances": {}, "batch_fingerprint": digest({j["key"]: j["fingerprint"] for j in jobs}),
        "mode": "functional", "time_load_affected": True, "parallelism_limit": batch["parallel"], "repetitions": 1,
        "random_seed": batch["seed"], "expected_instance_keys": [j["key"] for j in jobs]}
    lock, running_meta = threading.Lock(), {}
    def observe(key, metadata):
        with lock:
            if metadata is None:
                running_meta.pop(key, None)
            else:
                running_meta[key] = metadata
                metadata["concurrency_at_start"] = len(running_meta)
                for live in running_meta.values():
                    live["max_observed_concurrency"] = max(live["max_observed_concurrency"], len(running_meta))
    def execute(job):
        result = run_one(job, batch, monitor, observe)
        with lock:
            state["instances"][job["key"]] = result
            state["processed"] = len(state["instances"])
            state["ok"] = sum(r["status"] == "ok" for r in state["instances"].values())
            state["failed"] = state["processed"] - state["ok"]
            publish(root, state)
            print("[%d/%d] %s %s%s" % (state["processed"], len(jobs), job["key"], result["status"], " (reused)" if result["reused"] else ""), flush=True)
    publish(root, state)
    ordered = list(jobs)
    random.Random(batch["seed"]).shuffle(ordered)
    if batch["parallel"] == 1:
        for job in ordered:
            execute(job)
    elif not batch["auto_parallel"]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch["parallel"]) as pool:
            for future in [pool.submit(execute, job) for job in ordered]:
                future.result()
    else:
        slots = AdaptiveSlots(batch["parallel"])
        pending, running, last_sample = ordered, set(), -float("inf")
        psutil.cpu_percent(interval=None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch["parallel"]) as pool:
            while pending or running:
                timestamp = time.monotonic()
                if timestamp - last_sample >= 15:
                    cpu, memory = psutil.cpu_percent(interval=None), psutil.virtual_memory()
                    available = memory.available / 2**30
                    slots.update(timestamp, cpu, available)
                    with (root / "scheduler_load.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": now(), "host_cpu_percent": cpu, "host_memory_percent": memory.percent,
                            "available_memory_gib": available, "active_futures": len(running), "target_parallelism": slots.target,
                            "maximum_parallelism": slots.maximum}) + "\n")
                        f.flush()
                    last_sample = timestamp
                while pending and len(running) < slots.target:
                    running.add(pool.submit(execute, pending.pop(0)))
                if running:
                    completed, running = concurrent.futures.wait(running, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in completed:
                        future.result()
    state.update(status="completed" if state["ok"] == len(jobs) else "finished_with_failures", finished=True,
        complete_success=state["ok"] == len(jobs), ended_at=now())
    publish(root, state)
    return state

def load_entries(args, work):
    entries = []
    for spec in args.apk_dir:
        if "=" not in spec:
            raise ValueError("--apk-dir must be dataset=path")
        dataset, raw = spec.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", dataset):
            raise ValueError("invalid dataset label")
        directory = native_path(raw, work)
        apks = sorted(directory.glob("*.apk"))
        if not apks:
            raise ValueError("no APKs in dataset: " + spec)
        entries += [{"label": dataset + "__" + apk.stem, "dataset": dataset, "apk_path": str(apk), "size": apk.stat().st_size} for apk in apks]
    for source in args.apk_manifest:
        source = Path(source).resolve()
        doc = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(doc.get("apk_entries"), list):
            raise ValueError("APK manifest must have apk_entries list")
        entries.extend(doc["apk_entries"])
    if not entries or len({r["label"] for r in entries}) != len(entries):
        raise ValueError("empty APK collection or duplicate labels")
    for entry in entries:
        path = Path(entry["apk_path"]).resolve()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", entry["label"]) or not path.is_file() or path.suffix.lower() != ".apk":
            raise ValueError("invalid label / missing APK: " + entry["label"])
        if entry.get("size") is not None and path.stat().st_size != int(entry["size"]):
            raise ValueError("APK size changed since selection: " + str(path))
        if args.kind == "fd" and (work / "out/exp5_fd" / (entry["label"] + ".summary.csv")).exists():
            raise ValueError("existing E5 native export must not be rerun: " + entry["label"])
        actual = sha256(path)
        if entry.get("sha256_expected") and actual != entry["sha256_expected"]:
            raise ValueError("APK SHA-256 changed / disagrees with selected candidate: " + str(path))
        entry.update(apk_path=str(path), sha256_actual=actual, sha256_verified=True, size=path.stat().st_size)
    return entries

def main(argv=None, monitor=run_command):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind", choices=("gen8", "fd"))
    p.add_argument("name")
    p.add_argument("--apk-dir", action="append", default=[], help="dataset=path; may repeat")
    p.add_argument("--apk-manifest", action="append", default=[])
    p.add_argument("--configs", nargs="+")
    p.add_argument("--parallel", type=int, default=1)
    p.add_argument("--auto-parallel", action="store_true")
    p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--sample-interval", type=float, default=.5)
    p.add_argument("--xmx", default="8g")
    p.add_argument("--seed", type=int, default=20260930)
    p.add_argument("--work-root", default=r"C:\pdmm_work2")
    p.add_argument("--java")
    args = p.parse_args(argv)
    if args.parallel < 1 or args.timeout <= 0 or args.sample_interval <= 0:
        raise ValueError("parallel / timeout / sampling interval must be positive")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", args.name) or args.name in {".", "..", "exp5_fd", "exp5_dmmpp"}:
        raise ValueError("outName must be a safe new collection name (legacy E5 protected)")
    configs = args.configs or (GEN8_CONFIGS if args.kind == "gen8" else ["native"])
    if len(configs) != len(set(configs)) or any(c not in (GEN8_CONFIGS if args.kind == "gen8" else ["native"]) for c in configs):
        raise ValueError("unknown or duplicate export configuration")
    work = Path(args.work_root).resolve()
    java = Path(args.java or (r"C:\Program Files\Java\jdk1.8.0_121\bin\java.exe" if args.kind == "gen8"
                            else r"C:\Program Files\Java\jdk-17.0.1\bin\java.exe"))
    root = work / "out" / args.name
    batch = {"kind": args.kind, "name": args.name, "work": str(work), "root": str(root), "java": str(java), "xmx": args.xmx,
        "parallel": args.parallel, "auto_parallel": args.auto_parallel, "timeout": args.timeout, "sample_interval": args.sample_interval,
        "seed": args.seed, "batch_id": uuid.uuid4().hex}
    with FileLock(root / "runner.lock"), BatchRegistry(work, "functional", "exports:" + args.name):
        entries = load_entries(args, work)
        inputs = [java, HERE / "run_exports.py", HERE / "resource_monitor.py", HERE / "run_static.py",
                  work / ("lib/DMMPP.jar" if args.kind == "gen8" else "lib/flowdroid-2.15.1.jar")]
        if (java.parent.parent / "release").exists():
            inputs.append(java.parent.parent / "release")
        shared = [{"path": str(path.resolve()), "size": path.stat().st_size, "sha256": sha256(path)} for path in inputs]
        shared += tree_manifest(work / ("build8" if args.kind == "gen8" else "build17"), "*.class")
        shared += tree_manifest(work / "platforms", "android.jar")
        atomic_json(root / "inputs.json", {"schema_version": VERSION, "batch": batch, "shared_inputs": shared, "apk_entries": entries})
        jobs = []
        for entry in entries:
            for config in configs:
                parameters = {"schema_version": VERSION, "kind": args.kind, "shared_inputs": shared, "apk": entry,
                    "config": config, "timeout": args.timeout, "xmx": args.xmx, "parallel_limit": args.parallel,
                    "auto_parallel": args.auto_parallel, "sample_interval": args.sample_interval, "seed": args.seed,
                    "classpath_order": "build8;DMMPP.jar" if args.kind == "gen8" else "flowdroid-2.15.1.jar;build17"}
                key = entry["label"] + "." + config.replace("/", ".")
                directory_id = digest({"label": entry["label"], "config": config})[:16]
                jobs.append({**entry, "key": key, "config": config, "parameters": parameters, "fingerprint": digest(parameters),
                    "folder": str(root / "instances" / directory_id)})
        state = run_batch(batch, jobs, monitor)
    print("DONE %s expected=%d ok=%d failed=%d; functional resources are load-affected" % (args.name, state["expected"], state["ok"], state["failed"]))
    return 0 if state["complete_success"] else 1

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("export runner: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

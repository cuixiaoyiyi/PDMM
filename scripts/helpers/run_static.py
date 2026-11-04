#!/usr/bin/env python3
"""Recoverable, externally measured FlowDroid / Androlic instances.

Java CSVs retain their internal phase and GC measurements. resource.json stores
the separate process measurements, including failures/timeouts. Legacy CSV
existence or .done entries cannot establish measured completion.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time
import uuid
import psutil

HERE = Path(__file__).resolve().parent
VERSION = 2
RUN_COLS = ["label", "config", "status", "flows", "sources", "sinks", "cg_s", "taint_s", "path_s", "total_s", "fd_max_mb", "wall_s", "live_any_mb", "live_major_mb", "major_gcs", "edge_prop", "infoflow_prop", "alias_prop", "cg_edges", "reachable", "dmm_methods", "dmm_sites", "dmm_edges", "pdmm"]
ANDRO_COLS = ["label", "lifecycle", "params", "rep", "components", "generated", "failed", "spliced", "total_paths", "time_s", "live_any_mb", "live_major_mb", "major_gcs", "formals", "status"]
COMP_COLS = ["label", "lifecycle", "params", "rep", "component", "kind", "status", "formals", "paths", "time_s"]
PROPS = {
    "native": ["-Dpdmm.lifecycle=native"],
    "native_alias": ["-Dpdmm.lifecycle=native", "-Dpdmm.alias=1"],
    "hsm": ["-Dpdmm.lifecycle=hsm"],
    "hsm_tx": ["-Dpdmm.lifecycle=hsm", "-Dpdmm.txsite=1"],
    "hsm_tx_alias": ["-Dpdmm.lifecycle=hsm", "-Dpdmm.txsite=1", "-Dpdmm.alias=1"],
    "hsm_tx_alias_mand": ["-Dpdmm.lifecycle=hsm", "-Dpdmm.txsite=1", "-Dpdmm.alias=1", "-Dpdmm.phases=mandatory"],
}

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=True, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def atomic_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

def native_path(raw, base):
    if os.name == "nt" and len(raw) > 3 and raw[0] == "/" and raw[2] == "/" and raw[1].isalpha():
        raw = raw[1].upper() + ":" + raw[2:]
    path = Path(raw)
    return (path if path.is_absolute() else Path(base) / path).resolve()

def numeric(value, integer=False):
    n = float(value)
    if not math.isfinite(n) or n < 0 or (integer and int(n) != n):
        raise ValueError("invalid nonnegative numeric value: " + repr(value))
    return n

def csv_rows(path, width, header=None):
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("CSV missing final newline: " + str(path))
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True))
    if any(len(r) != width for r in rows):
        raise ValueError("CSV column count mismatch: " + str(path))
    if header is not None:
        if not rows or rows[0] != header:
            raise ValueError("CSV header mismatch: " + str(path))
        rows = rows[1:]
    return rows

def validate_outputs(kind, attempt, label, config, rep):
    attempt = Path(attempt)
    if kind == "taint":
        runpath = attempt / (label + "." + config + ".run.csv")
        detailpath = attempt / (label + "." + config + ".flows.csv")
        runs = csv_rows(runpath, 24)
        if len(runs) != 1:
            raise ValueError("expected one run row")
        row = runs[0]
        if row[:3] != [label, config, "OK"] or not row[23]:
            raise ValueError("Java run is not a complete OK result")
        for i in range(3, 23):
            numeric(row[i], integer=i != 11)
        detail = csv_rows(detailpath, 6)
        if len(detail) != int(row[3]) or any(r[:2] != [label, config] for r in detail):
            raise ValueError("flow count/identity mismatch")
    else:
        lc, pm = config.split("/")
        runpath = attempt / "java.run.csv"
        detailpath = attempt / "java.run.components.csv"
        runs = csv_rows(runpath, 15, ANDRO_COLS)
        if len(runs) != 1:
            raise ValueError("expected one Androlic run row")
        row = runs[0]
        if row[:4] != [label, lc, pm, str(rep)] or row[14] != "OK":
            raise ValueError("Androlic run not OK")
        for i in range(4, 14):
            numeric(row[i], integer=i != 9)
        detail = csv_rows(detailpath, 10, COMP_COLS)
        if int(row[6]) != 0 or sum(int(row[i]) for i in (5, 6, 7)) != int(row[4]):
            raise ValueError("component generation incomplete")
        if len(detail) != int(row[4]) or len({r[4] for r in detail}) != len(detail):
            raise ValueError("missing/duplicate components")
        for component in detail:
            if component[:4] != row[:4] or component[6] not in {"OK", "SPLICED"}:
                raise ValueError("component failed/mismatched")
            for i in (7, 8, 9):
                numeric(component[i], integer=i != 9)
        if sum(int(r[8]) for r in detail) != int(row[8]) or sum(r[6] == "SPLICED" for r in detail) != int(row[7]):
            raise ValueError("component path/spliced counts disagree")
    files = [{"path": str(p), "size": p.stat().st_size, "sha256": sha256(p)} for p in (runpath, detailpath)]
    return {"run_row": row, "detail_rows": detail, "files": files}

def resource_valid(resource):
    wall = resource.get("wall_seconds")
    return (resource.get("status") == "ok" and resource.get("exit_code") == 0
            and isinstance(wall, (int, float)) and math.isfinite(wall) and wall >= 0
            and resource.get("started_at") and resource.get("ended_at")
            and "peak_root_working_set_bytes" in resource and "peak_tree_sampled_working_set_bytes" in resource
            and "sample_interval_s" in resource and "memory_missing_reason" in resource
            and (resource["peak_root_working_set_bytes"] is not None or bool(resource["memory_missing_reason"])))

def completed_attempt(kind, folder, signature, label, config, rep):
    try:
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        resource = json.loads((folder / "resource.json").read_text(encoding="utf-8"))
        if result.get("fingerprint") != signature or result.get("status") != "ok" or not resource_valid(resource):
            return None
        if resource.get("metadata", {}).get("fingerprint") != signature:
            return None
        validated = validate_outputs(kind, folder, label, config, rep)
        if result.get("outputs") != validated["files"]:
            return None
        return {**result, "validated": validated}
    except (OSError, ValueError, KeyError, csv.Error):
        return None

class FileLock:
    def __init__(self, path):
        self.path = Path(path)
        self.owned = False
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                with self.path.open("x", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "create_time": psutil.Process().create_time(), "started_at": now()}, f)
                self.owned = True
                return self
            except FileExistsError:
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    alive = abs(psutil.Process(data["pid"]).create_time() - data["create_time"]) < .1
                except (OSError, ValueError, KeyError, psutil.Error):
                    alive = time.time() - self.path.stat().st_mtime < 60
                if alive:
                    raise RuntimeError("active runner lock: " + str(self.path))
                self.path.rename(self.path.with_name(self.path.name + ".stale." + uuid.uuid4().hex))
        raise RuntimeError("cannot acquire lock: " + str(self.path))
    def __exit__(self, *args):
        if self.owned:
            self.path.unlink(missing_ok=True)

class BatchRegistry:
    """Formal timings cannot overlap other registered static batches."""
    def __init__(self, root, mode, collection):
        self.folder = Path(root) / ".static_registry"
        self.mode, self.collection = mode, collection
        self.path = self.folder / (uuid.uuid4().hex + ".json")
    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with FileLock(self.folder / "registry.lock"):
            for path in self.folder.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    alive = abs(psutil.Process(data["pid"]).create_time() - data["create_time"]) < .1
                except (OSError, ValueError, KeyError, psutil.Error):
                    alive = False
                if alive and (self.mode == "performance" or data.get("mode") == "performance" or data.get("collection") == self.collection):
                    raise RuntimeError("conflicting static batch active: " + str(path))
            atomic_json(self.path, {"pid": os.getpid(), "create_time": psutil.Process().create_time(), "mode": self.mode,
                                    "collection": self.collection, "started_at": now()})
        return self
    def __exit__(self, *args):
        self.path.unlink(missing_ok=True)

def tree_manifest(path, pattern):
    files = sorted(Path(path).rglob(pattern))
    if not files:
        raise ValueError("required input tree is empty: " + str(path))
    return [{"path": str(p.resolve()), "size": p.stat().st_size, "sha256": sha256(p)} for p in files]

def input_manifest(work, kind, java, ss):
    paths = [java, HERE / "run_static.py", HERE / "resource_monitor.py"]
    paths += [work / "lib/flowdroid-2.15.1.jar", ss] if kind == "taint" else [work / "lib/DMMPP.jar", work / "lib/Androlic_DMMPP.jar"]
    files = [{"path": str(p.resolve()), "size": p.stat().st_size, "sha256": sha256(p)} for p in paths]
    files += tree_manifest(work / ("build17" if kind == "taint" else "build8"), "*.class")
    files += tree_manifest(work / "platforms", "android.jar")
    return files

def command_for(job, batch, attempt):
    work, java, apk = Path(batch["work"]), Path(batch["java"]), Path(job["apk"])
    label, config, rep = job["label"], job["config"], job["rep"]
    base = [str(java), "-Duser.language=en", "-Duser.country=US", "-Xmx" + batch["xmx"]]
    if batch["kind"] == "taint":
        return base + PROPS[config] + ["-cp", str(work / "build17") + os.pathsep + str(work / "lib/flowdroid-2.15.1.jar"), "rev.TaintRun",
                 str(work / "platforms"), str(apk), batch["ss"], str(attempt), label, config, batch["cg"], str(batch["timeout"])]
    cfg = attempt / "androlic.cfg"
    cfg.write_text("\n".join([
        "androidPath " + str(work / "platforms"), "apkBasePath " + str(apk.parent), "apkName " + apk.name,
        "outputBasePath " + str(attempt / "androlic_output"), "javaHome " + str(java.parent.parent),
        "maxRunningTime " + str(batch["timeout"] * 1000), "maxPathNumber " + str(batch["maxpaths"]), "maxPathLength 10000",
        "maxContextDepth 4", "maxRecursiveInvocationLevel 3", "maxLoopUnrollNumber 2", "debugMode 0", "isJimpleOutput 0", "entryMethod DMMPP", ""
    ]), encoding="utf-8")
    lc, pm = config.split("/")
    return base + ["-cp", str(work / "build8") + os.pathsep + str(work / "lib/Androlic_DMMPP.jar"), "rev8.Androlic8", lc, pm,
                   str(cfg), str(attempt / "java.run.csv"), label, str(rep)]

def run_instance(job, batch, monitor, concurrency, observe=None):
    attempts = Path(job["folder"]) / "attempts"
    if attempts.exists():
        for folder in sorted(attempts.iterdir(), reverse=True):
            reused = completed_attempt(batch["kind"], folder, job["fingerprint"], job["label"], job["config"], job["rep"])
            if reused:
                return {**reused, "reused": True}
    attempt = attempts / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "." + uuid.uuid4().hex[:12])
    attempt.mkdir(parents=True)
    atomic_json(attempt / "inputs.json", {"fingerprint": job["fingerprint"], "parameters": job["parameters"]})
    metadata = {"experiment": batch["name"], "kind": batch["kind"], "label": job["label"], "config": job["config"], "repetition": job["rep"],
        "fingerprint": job["fingerprint"], "mode": batch["mode"], "requested_parallelism": batch["parallel"], "concurrency_at_start": concurrency(),
        "time_load_affected": batch["mode"] == "functional", "random_seed": batch["seed"], "batch_id": batch.get("batch_id")}
    metadata["max_observed_concurrency"] = metadata["concurrency_at_start"]
    if observe:
        observe(job["key"], metadata)
    started_at, t0 = now(), time.perf_counter()
    try:
        command = command_for(job, batch, attempt)
        resource = monitor(command, cwd=batch["work"], log_path=str(attempt / "process.log"), record_path=str(attempt / "resource.json"),
                           timeout_s=batch["timeout"], metadata=metadata, sample_interval_s=batch["sample_interval"])
    except Exception as exc:
        resource = {"status": "launch_error", "exit_code": None, "started_at": started_at, "ended_at": now(),
                    "wall_seconds": time.perf_counter() - t0, "error": repr(exc), "metadata": metadata,
                    "peak_root_working_set_bytes": None, "peak_tree_sampled_working_set_bytes": None,
                    "sample_interval_s": batch["sample_interval"], "memory_missing_reason": "no completed process measurement"}
    finally:
        if observe:
            observe(job["key"], None)
    resource["metadata"] = metadata
    atomic_json(attempt / "resource.json", resource)
    status, error, validated = resource.get("status", "failed"), None, None
    if resource_valid(resource):
        try:
            validated = validate_outputs(batch["kind"], attempt, job["label"], job["config"], job["rep"])
            status = "ok"
        except (OSError, ValueError, csv.Error) as exc:
            status, error = "invalid_output", str(exc)
    result = {"schema_version": VERSION, "kind": batch["kind"], "label": job["label"], "config": job["config"], "rep": job["rep"],
              "fingerprint": job["fingerprint"], "attempt": str(attempt), "status": status, "validation_error": error,
              "resource_record": str(attempt / "resource.json"), "external_wall_seconds": resource.get("wall_seconds"),
              "exit_code": resource.get("exit_code"), "outputs": validated["files"] if validated else [], "ended_at": now(),
              "internal_metrics": "Java CSV" if validated else "missing or unsuccessful Java output retained"}
    result.update({"started_at": resource.get("started_at"), "process_ended_at": resource.get("ended_at"),
        "peak_root_working_set_bytes": resource.get("peak_root_working_set_bytes"),
        "peak_tree_sampled_working_set_bytes": resource.get("peak_tree_sampled_working_set_bytes"),
        "sample_interval_s": resource.get("sample_interval_s"), "memory_missing_reason": resource.get("memory_missing_reason"),
        "concurrency_at_start": metadata["concurrency_at_start"], "max_observed_concurrency": metadata["max_observed_concurrency"],
        "requested_parallelism": batch["parallel"], "time_load_affected": batch["mode"] == "functional"})
    atomic_json(attempt / "result.json", result)
    return {**result, "validated": validated, "reused": False}

def archive(path, root):
    if path.exists():
        folder = root / "history"
        folder.mkdir(exist_ok=True)
        target = folder / (path.name + "." + sha256(path))
        if not target.exists():
            shutil.copy2(path, target)

def publish(batch, results):
    root, work = Path(batch["root"]), Path(batch["work"])
    rows, details, reps = [], [], [["label", "config", "rep", "attempt", "fingerprint"]]
    for key in sorted(results):
        result, valid = results[key], results[key].get("validated")
        if valid:
            reps.append([result["label"], result["config"], result["rep"], result["attempt"], result["fingerprint"]])
            if batch["kind"] == "androlic" or result["rep"] == 1:
                rows.append(valid["run_row"])
                details.extend(valid["detail_rows"])
        elif batch["kind"] == "taint" and result["rep"] == 1:
            # Java values are missing, not invented zeroes. Actual external
            # duration / peak memory remain in resource.json and instances.csv.
            rows.append([result["label"], result["config"], "FAIL:" + result["status"]] + [""] * 21)
        elif batch["kind"] == "androlic":
            lc, pm = result["config"].split("/")
            rows.append([result["label"], lc, pm, str(result["rep"])] + [""] * 10 + ["FAIL:" + result["status"]])
    if batch["kind"] == "taint":
        runpath = work / "out" / (batch["name"] + ".runs.csv")
        detailpath = work / "out" / (batch["name"] + ".flows.csv")
    else:
        runpath = work / "androlic/results" / (batch["name"] + ".csv")
        detailpath = runpath.with_name(batch["name"] + ".components.csv")
        rows.insert(0, ANDRO_COLS)
        details.insert(0, COMP_COLS)
    if not batch.get("_archived"):
        for path in (runpath, detailpath):
            archive(path, root)
        batch["_archived"] = True
    atomic_csv(runpath, rows)
    atomic_csv(detailpath, details)
    atomic_csv(root / "repetitions.csv", reps)
    instances = [["label", "config", "rep", "status", "started_at", "process_ended_at", "external_wall_seconds", "exit_code",
                  "peak_root_working_set_bytes", "peak_tree_sampled_working_set_bytes", "sample_interval_s", "memory_missing_reason",
                  "concurrency_at_start", "max_observed_concurrency", "requested_parallelism", "time_load_affected", "attempt", "resource_record"]]
    instances += [[r.get(k, "") for k in instances[0]] for _, r in sorted(results.items())]
    atomic_csv(root / "instances.csv", instances)

class AdaptiveSlots:
    def __init__(self, maximum):
        self.maximum, self.target, self.steady_since = maximum, 1, None
    def update(self, timestamp, cpu, available_gib):
        if available_gib < 8 or cpu > 85:
            self.target = max(1, self.target - 1)
            self.steady_since = None
        elif cpu < 60 and available_gib >= 16:
            if self.steady_since is None:
                self.steady_since = timestamp
            elif timestamp - self.steady_since >= 60:
                self.target = min(self.maximum, self.target + 1)
                self.steady_since = timestamp
        else:
            self.steady_since = None
        return self.target

def run_batch(batch, jobs, monitor):
    root = Path(batch["root"])
    root.mkdir(parents=True, exist_ok=True)
    state = {"schema_version": VERSION, "status": "running", "finished": False, "complete_success": False, "started_at": now(),
        "kind": batch["kind"], "name": batch["name"], "mode": batch["mode"], "expected": len(jobs), "processed": 0, "ok": 0, "failed": 0,
        "parallelism": batch["parallel"], "repetitions": batch["reps"], "random_seed": batch["seed"], "time_load_affected": batch["mode"] == "functional",
        "legacy_aggregate_projection": "taint rep1 only for scoring; all repeats in instances.csv and repetitions.csv; Androlic includes all repeats",
        "batch_fingerprint": digest({j["key"]: j["fingerprint"] for j in jobs}), "instances": {},
        "legacy_external_metrics": "missing; legacy files never qualify for measured reuse"}
    atomic_json(root / "state.json", state)
    lock, results, active, peak = threading.Lock(), {}, 0, 0
    running_metadata = {}
    def concurrency():
        with lock:
            return active
    def observe(key, metadata):
        with lock:
            if metadata is None:
                running_metadata.pop(key, None)
            else:
                running_metadata[key] = metadata
                for running in running_metadata.values():
                    running["max_observed_concurrency"] = max(running["max_observed_concurrency"], len(running_metadata))
    def execute(job):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            result = run_instance(job, batch, monitor, concurrency, observe)
        finally:
            with lock:
                active -= 1
        with lock:
            results[job["key"]] = result
            state["instances"][job["key"]] = {k: v for k, v in result.items() if k != "validated"}
            state.update(processed=len(results), ok=sum(r["status"] == "ok" for r in results.values()), peak_parallelism=peak)
            state["failed"] = state["processed"] - state["ok"]
            atomic_json(root / "state.json", state)
            publish(batch, results)
            print("[%d/%d] %s %s%s" % (len(results), len(jobs), job["key"], result["status"], " (reused)" if result["reused"] else ""), flush=True)
    ordered = list(jobs)
    random.Random(batch["seed"]).shuffle(ordered)
    if batch["parallel"] == 1:
        for job in ordered:
            execute(job)
    elif not batch.get("auto_parallel"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch["parallel"]) as pool:
            for future in [pool.submit(execute, job) for job in ordered]:
                future.result()
    else:
        slots = AdaptiveSlots(batch["parallel"])
        pending, running, last_sample = list(ordered), set(), -float("inf")
        psutil.cpu_percent(interval=None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch["parallel"]) as pool:
            while pending or running:
                timestamp = time.monotonic()
                if timestamp - last_sample >= 15:
                    cpu = psutil.cpu_percent(interval=None)
                    memory = psutil.virtual_memory()
                    available = memory.available / 2**30
                    slots.update(timestamp, cpu, available)
                    with (root / "scheduler_load.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": now(), "cpu_percent": cpu, "memory_percent": memory.percent,
                            "available_memory_gib": available, "target_parallelism": slots.target,
                            "active_futures": len(running), "maximum_parallelism": slots.maximum}) + "\n")
                        f.flush()
                    last_sample = timestamp
                while pending and len(running) < slots.target:
                    running.add(pool.submit(execute, pending.pop(0)))
                if running:
                    completed, running = concurrent.futures.wait(running, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in completed:
                        future.result()
    state.update(status="completed" if state["ok"] == len(jobs) else "finished_with_failures", finished=True,
                 complete_success=state["ok"] == len(jobs), ended_at=now(), peak_parallelism=peak)
    atomic_json(root / "state.json", state)
    return state

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("taint", "androlic"):
        p = sub.add_parser(kind)
        p.add_argument("apk_dir")
        p.add_argument("name")
        p.add_argument("parallel_or_reps", type=int)
        p.add_argument("configs", nargs="+")
        p.add_argument("--mode", choices=("functional", "performance"))
        p.add_argument("--reps", type=int)
        p.add_argument("--work-root", default=os.environ.get("PDMM_WORK_ROOT", r"C:\pdmm_work2"))
        p.add_argument("--callgraph", choices=("SPARK", "CHA"), default="SPARK")
        p.add_argument("--sources-sinks", default="lib/fd_res/SourcesAndSinks.txt")
        p.add_argument("--seed", type=int, default=20260930)
        p.add_argument("--sample-interval", type=float, default=.5)
        p.add_argument("--auto-parallel", action="store_true", default=os.environ.get("TAINT_AUTO_PARALLEL") == "1")
    return parser.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)
    kind = args.kind
    mode = args.mode or os.environ.get("TAINT_MODE" if kind == "taint" else "ANDROLIC_MODE", "functional" if kind == "taint" else "performance")
    if mode not in {"functional", "performance"}:
        raise ValueError("invalid mode")
    if not args.name or len(args.name) > 64 or args.name in {".", ".."} or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in args.name):
        raise ValueError("outName must be one safe directory name")
    work = Path(args.work_root).resolve()
    apk_dir = native_path(args.apk_dir, work)
    apks = sorted(apk_dir.glob("*.apk"))
    if not apks:
        raise ValueError("no APKs found: " + str(apk_dir))
    configs = args.configs
    if len(configs) != len(set(configs)):
        raise ValueError("duplicate configuration")
    allowed = set(PROPS) if kind == "taint" else {lc + "/" + pm for lc in ("fixed", "hsm") for pm in ("perarg", "pertype", "rules")}
    if any(c not in allowed for c in configs):
        raise ValueError("unknown configuration")
    if args.parallel_or_reps < 1 or args.sample_interval <= 0:
        raise ValueError("parallelism/reps/sample interval must be positive")
    if mode == "performance":
        if args.auto_parallel:
            raise ValueError("formal performance cannot use adaptive parallelism")
        if kind == "taint" and args.parallel_or_reps != 1:
            raise ValueError("formal taint performance requires parallel=1")
        if args.reps is not None and args.reps != 5:
            raise ValueError("formal performance requires five repetitions")
        parallel, reps, timeout = 1, 5, 1800
        if kind == "androlic" and args.parallel_or_reps != 5:
            print("formal protocol: legacy reps=%d upgraded to 5" % args.parallel_or_reps, flush=True)
    else:
        parallel = args.parallel_or_reps if kind == "taint" else 1
        reps = (args.reps or int(os.environ.get("TAINT_REPS", "1"))) if kind == "taint" else (args.reps or args.parallel_or_reps)
        timeout = int(os.environ.get("TAINT_TIMEOUT" if kind == "taint" else "ANDROLIC_TIMEOUT", "1800"))
    if timeout < 1 or reps < 1:
        raise ValueError("timeout/reps must be positive")
    java = Path(os.environ.get("TAINT_JAVA" if kind == "taint" else "ANDROLIC_JAVA", r"C:\Program Files\Java\jdk-17.0.1\bin\java.exe"
                               if kind == "taint" else r"C:\Program Files\Java\jdk1.8.0_121\bin\java.exe"))
    ss = native_path(args.sources_sinks, work) if kind == "taint" else None
    root = work / ("out" if kind == "taint" else "androlic/results") / args.name
    batch = {"kind": kind, "name": args.name, "work": str(work), "root": str(root), "java": str(java), "mode": mode,
        "parallel": parallel, "reps": reps, "timeout": timeout, "seed": args.seed, "sample_interval": args.sample_interval,
        "cg": args.callgraph, "ss": str(ss) if ss else None, "maxpaths": int(os.environ.get("ANDROLIC_MAXPATHS", "500")),
        "xmx": os.environ.get("TAINT_XMX" if kind == "taint" else "ANDROLIC_XMX", "12g"), "batch_id": uuid.uuid4().hex,
        "auto_parallel": kind == "taint" and args.auto_parallel}
    if batch["maxpaths"] <= 0:
        raise ValueError("maxPathNumber must be positive")
    with FileLock(root / "runner.lock"), BatchRegistry(work, mode, kind + ":" + args.name):
        manifest = input_manifest(work, kind, java, ss)
        atomic_json(root / "inputs.json", {"schema_version": VERSION, "batch": batch, "shared_inputs": manifest})
        jobs = []
        for apk in apks:
            apk_hash = sha256(apk)
            for config in configs:
                for rep in range(1, reps + 1):
                    params = {"schema_version": VERSION, "inputs": manifest, "apk": str(apk), "apk_sha256": apk_hash, "config": config,
                        "rep": rep, "mode": mode, "parallel": parallel, "reps": reps, "timeout": timeout, "cg": batch["cg"],
                        "maxpaths": batch["maxpaths"], "xmx": batch["xmx"], "seed": args.seed, "sample_interval": args.sample_interval}
                    key = apk.stem + "." + config.replace("/", ".") + ".rep" + str(rep)
                    # Java 8 and this Windows host cannot rely on long-path
                    # support. The manifest retains readable identities while
                    # physical instance directories use a compact stable hash.
                    directory_id = digest({"label": apk.stem, "config": config, "rep": rep})[:16]
                    jobs.append({"key": key, "label": apk.stem, "apk": str(apk), "config": config, "rep": rep,
                        "folder": str(root / "instances" / directory_id), "fingerprint": digest(params), "parameters": params})
        from resource_monitor import run_command
        state = run_batch(batch, jobs, run_command)
    print("DONE %s expected=%d ok=%d failed=%d mode=%s" % (args.name, state["expected"], state["ok"], state["failed"], mode))
    return 0 if state["complete_success"] else 1

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print("static runner: " + str(exc), file=sys.stderr)
        raise SystemExit(2)

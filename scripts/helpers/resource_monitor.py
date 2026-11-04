"""External process measurements; JVM heap/stage CSVs remain separate.

Windows RSS from psutil is the process Working Set. Tree peaks are sampled
simultaneous sums of unique PID/create-time identities, not sums of per-process
peaks. Shared pages may occur in several processes and are not de-duplicated.
Only processes launched by run_command are terminated on its timeout.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil

SCHEMA_VERSION = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2, allow_nan=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temporary, path)


class ProcessMonitor:
    def __init__(self, root_pids, sample_interval_s=0.5):
        if sample_interval_s <= 0:
            raise ValueError("sample interval must be positive")
        if not isinstance(root_pids, dict):
            root_pids = {"experiment": list(root_pids)}
        self.sample_interval_s = float(sample_interval_s)
        self.groups = {}
        self.errors = set()
        self.host_cpu = []
        self.host_memory = []
        self.host_available = []
        self.sample_times = []
        self._stop = threading.Event()
        self._thread = None
        self._finished = None
        for name, pids in root_pids.items():
            group = {"roots": {}, "known": {}, "details": {}, "peak_root": None,
                     "peak_tree": None, "samples": 0}
            for pid in set(pids):
                try:
                    proc = psutil.Process(pid)
                    identity = (pid, proc.create_time())
                    group["roots"][identity] = proc
                    group["known"][identity] = proc
                except (psutil.Error, OSError) as exc:
                    self.errors.add(f"{name} root {pid}: {type(exc).__name__}")
            self.groups[name] = group

    def start(self):
        if self._thread is not None:
            raise RuntimeError("monitor already started")
        self.started_at = utc_now()
        self.started_perf = time.perf_counter()
        psutil.cpu_percent(interval=None)
        self._sample(include_cpu=False)
        self._thread = threading.Thread(target=self._loop, name="resource-sampler", daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        psutil.cpu_percent(interval=None)
        while not self._stop.wait(self.sample_interval_s):
            try:
                self._sample()
            except Exception as exc:
                self.errors.add(f"sampler: {type(exc).__name__}: {exc}")

    def _sample(self, include_cpu=True):
        self.sample_times.append(time.perf_counter())
        if include_cpu:
            self.host_cpu.append(psutil.cpu_percent(interval=None))
        mem = psutil.virtual_memory()
        self.host_memory.append(mem.percent)
        self.host_available.append(mem.available)
        for name, group in self.groups.items():
            for identity, proc in list(group["known"].items()):
                try:
                    if not proc.is_running() or psutil.Process(proc.pid).create_time() != identity[1]:
                        group["known"].pop(identity, None)
                        continue
                    for child in proc.children(recursive=True):
                        key = (child.pid, child.create_time())
                        group["known"][key] = child
                except psutil.NoSuchProcess:
                    group["known"].pop(identity, None)
                    continue
                except (psutil.Error, OSError) as exc:
                    self.errors.add(f"{name} descendants: {type(exc).__name__}")
            tree_sum = root_sum = 0
            measured = root_measured = 0
            for identity, proc in list(group["known"].items()):
                try:
                    if not proc.is_running() or psutil.Process(proc.pid).create_time() != identity[1]:
                        group["known"].pop(identity, None)
                        continue
                    mi = proc.memory_info()
                    ct = proc.cpu_times()
                    cpu = ct.user + ct.system
                    detail = group["details"].get(identity)
                    if detail is None:
                        detail = {"pid": identity[0], "create_time": identity[1],
                                  "is_root": identity in group["roots"],
                                  "name": proc.name(), "cpu_initial_s": cpu,
                                  "cpu_last_s": cpu, "peak_working_set_bytes": 0,
                                  "os_peak_working_set_bytes": None,
                                  "peak_private_bytes": None, "samples": 0}
                        group["details"][identity] = detail
                    detail["cpu_last_s"] = max(detail["cpu_last_s"], cpu)
                    detail["peak_working_set_bytes"] = max(detail["peak_working_set_bytes"], mi.rss)
                    peak = getattr(mi, "peak_wset", None)
                    if peak is not None:
                        detail["os_peak_working_set_bytes"] = max(detail["os_peak_working_set_bytes"] or 0, peak)
                    private = getattr(mi, "private", None)
                    if private is not None:
                        detail["peak_private_bytes"] = max(detail["peak_private_bytes"] or 0, private)
                    detail["samples"] += 1
                    tree_sum += mi.rss
                    measured += 1
                    if identity in group["roots"]:
                        root_sum += mi.rss
                        root_measured += 1
                except psutil.NoSuchProcess:
                    group["known"].pop(identity, None)
                    continue
                except (psutil.Error, OSError) as exc:
                    self.errors.add(f"{name} process {identity[0]}: {type(exc).__name__}")
            if measured:
                group["samples"] += 1
                group["peak_tree"] = max(group["peak_tree"] or 0, tree_sum)
            if root_measured:
                group["peak_root"] = max(group["peak_root"] or 0, root_sum)

    def finish(self):
        if self._finished is not None:
            return self._finished
        if self._thread is None:
            raise RuntimeError("monitor has not started")
        self._stop.set()
        self._thread.join()
        self._sample(include_cpu=False)
        ended_perf = time.perf_counter()
        groups = {}
        for name, group in self.groups.items():
            details = []
            for detail in group["details"].values():
                d = dict(detail)
                # Existing emulator/self processes: CPU is the increment since
                # first sample, rather than their cumulative lifetime CPU.
                d["cpu_sampled_delta_s"] = max(0, d.pop("cpu_last_s") - d.pop("cpu_initial_s"))
                details.append(d)
            groups[name] = {
                "root_pids": [i[0] for i in group["roots"]],
                "sample_count": group["samples"],
                "peak_root_working_set_bytes": group["peak_root"],
                "peak_tree_sampled_working_set_bytes": group["peak_tree"],
                "peak_process_working_set_bytes": max((d["peak_working_set_bytes"] for d in details), default=None),
                "cpu_sampled_delta_s": sum(d["cpu_sampled_delta_s"] for d in details) if details else None,
                "processes": details,
                "missing_reason": None if details else "no process memory sample available",
            }
        gaps = [b-a for a,b in zip(self.sample_times, self.sample_times[1:])]
        self._finished = {
            "schema_version": SCHEMA_VERSION,
            "started_at": self.started_at, "ended_at": utc_now(),
            "wall_seconds": ended_perf - self.started_perf,
            "sample_interval_s": self.sample_interval_s,
            "actual_max_sample_gap_s": max(gaps, default=None),
            "memory_metric": "Windows process Working Set" if os.name == "nt" else "process RSS",
            "tree_peak_definition": "maximum sampled simultaneous sum of unique PID/create-time processes; shared pages counted per process",
            "short_lived_process_limitation": "processes that exit between samples may be absent; OS root peak provided when available",
            "group_overlap_definition": "groups reported separately; do not add their peaks",
            "groups": groups,
            "host_cpu_percent": {"mean": sum(self.host_cpu)/len(self.host_cpu) if self.host_cpu else None,
                                 "max": max(self.host_cpu, default=None), "samples": len(self.host_cpu)},
            "host_memory_percent": {"mean": sum(self.host_memory)/len(self.host_memory) if self.host_memory else None,
                                    "max": max(self.host_memory, default=None)},
            "host_min_available_memory_bytes": min(self.host_available, default=None),
            "sampling_errors": sorted(self.errors),
        }
        return self._finished


def _windows_handle_peak(handle):
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    api.restype = ctypes.c_int
    if not api(int(handle), ctypes.byref(counters), counters.cb):
        return None
    return {"peak_working_set_bytes": counters.PeakWorkingSetSize,
            "peak_pagefile_bytes": counters.PeakPagefileUsage,
            "final_private_bytes": counters.PrivateUsage}


def _terminate_owned_tree(proc, identity):
    errors = []
    try:
        root = psutil.Process(proc.pid)
        if root.create_time() != identity:
            return ["PID reused; refused termination"]
        owned = root.children(recursive=True) + [root]
        # This tree was launched by this wrapper; external emulator/servers
        # must be passed to ProcessMonitor only, never to this helper.
        for p in reversed(owned):
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                errors.append(str(exc))
        _, alive = psutil.wait_procs(owned, timeout=5)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                errors.append(str(exc))
    except psutil.NoSuchProcess:
        pass
    except psutil.Error as exc:
        errors.append(str(exc))
    return errors


def run_command(command, *, cwd, log_path, record_path, timeout_s=None, metadata=None, sample_interval_s=0.5):
    if not command or not all(isinstance(s, str) for s in command):
        raise ValueError("command must be a nonempty list of strings")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": SCHEMA_VERSION, "command": command, "cwd": str(Path(cwd).resolve()),
              "command_sha256": hashlib.sha256(json.dumps(command, ensure_ascii=False).encode()).hexdigest(),
              "metadata": metadata or {}, "timeout_s": timeout_s,
              "started_at": utc_now(), "ended_at": None, "wall_seconds": None,
              "status": "running", "exit_code": None, "pid": None, "resources": None,
              "os_root_peak_working_set_bytes": None, "error": None}
    atomic_json(record_path, record)
    t0 = time.perf_counter()
    monitor = proc = None
    identity = None
    interruption = None
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            record["pid"] = proc.pid
            try:
                identity = psutil.Process(proc.pid).create_time()
            except psutil.NoSuchProcess:
                identity = None  # a very short successful command may already have exited
            monitor = ProcessMonitor({"experiment": [proc.pid]}, sample_interval_s).start()
            atomic_json(record_path, record)
            try:
                record["exit_code"] = proc.wait(timeout=timeout_s)
                record["status"] = "ok" if proc.returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                record["status"] = "timeout"
                record["termination_errors"] = _terminate_owned_tree(proc, identity)
                try:
                    record["exit_code"] = proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    record["error"] = "owned process did not exit after timeout termination"
            if os.name == "nt":
                record["os_root_memory"] = _windows_handle_peak(proc._handle)
                if record["os_root_memory"]:
                    record["os_root_peak_working_set_bytes"] = record["os_root_memory"]["peak_working_set_bytes"]
        except (KeyboardInterrupt, SystemExit) as exc:
            interruption = exc
            record["status"] = "interrupted"
            record["error"] = f"{type(exc).__name__}: {exc}"
            if proc is not None and proc.poll() is None:
                record["termination_errors"] = _terminate_owned_tree(proc, identity)
                try:
                    record["exit_code"] = proc.wait(timeout=10)
                except subprocess.TimeoutExpired as cleanup_exc:
                    record["cleanup_error"] = str(cleanup_exc)
        except Exception as exc:
            record["status"] = "launch_error" if proc is None else "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            if proc is not None and proc.poll() is None:
                try:
                    record["termination_errors"] = _terminate_owned_tree(proc, identity)
                    record["exit_code"] = proc.wait(timeout=10)
                except (psutil.Error, subprocess.TimeoutExpired) as cleanup_exc:
                    record["cleanup_error"] = str(cleanup_exc)
        finally:
            # Wall time includes process creation/wait/timeout cleanup, never
            # a configured timeout substituted for the actual duration.
            record["ended_at"] = utc_now()
            record["wall_seconds"] = time.perf_counter() - t0
            if monitor is not None:
                try:
                    record["resources"] = monitor.finish()
                except Exception as exc:
                    record["measurement_error"] = f"{type(exc).__name__}: {exc}"
            group = ((record["resources"] or {}).get("groups") or {}).get("experiment", {})
            root_os_peaks = [d["os_peak_working_set_bytes"] for d in group.get("processes", [])
                             if d["is_root"] and d["os_peak_working_set_bytes"] is not None]
            if record["os_root_peak_working_set_bytes"] is not None:
                root_os_peaks.append(record["os_root_peak_working_set_bytes"])
            record["os_root_peak_working_set_bytes"] = max(root_os_peaks, default=None)
            root_peaks = [x for x in (record["os_root_peak_working_set_bytes"], group.get("peak_root_working_set_bytes")) if x is not None]
            record["peak_root_working_set_bytes"] = max(root_peaks, default=None)
            record["root_peak_definition"] = "maximum of OS-reported root lifetime peaks queried during/after execution and sampled root Working Set/RSS"
            record["peak_tree_sampled_working_set_bytes"] = group.get("peak_tree_sampled_working_set_bytes")
            record["sample_interval_s"] = float(sample_interval_s)
            record["memory_metric"] = "Windows process Working Set" if os.name == "nt" else "process RSS"
            record["memory_missing_reason"] = None if record["peak_root_working_set_bytes"] is not None else "process memory unavailable; see error/sampling_errors"
            atomic_json(record_path, record)
    if interruption is not None:
        raise interruption
    return record

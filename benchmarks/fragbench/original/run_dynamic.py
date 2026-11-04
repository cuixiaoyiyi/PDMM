#!/usr/bin/env python3
"""Durable dynamic FragBench cases on one already started emulator.

Usage: FB_VARIANT=androidx FB_RUN_SUFFIX=_20261008 python run_dynamic.py 29
Fresh output: dyn/api29x_20261008; old dyn/api29x is preserved. Failed,
interrupted and invalid cases retry on the next invocation. Completed cases
skip only after artifact validation. check_dynamic_complete.py gates queues.
`seconds` is the UI phase; `wall_s` includes reboot, install, collection,
cleanup and monitoring. Host Working Set and Android PSS/RSS remain separate.
"""
import argparse
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from check_dynamic_complete import CASE_IDS, CSV_FIELDS, SCHEMA, context_digest, digest, evaluate, load_json, valid_case

W = Path(r"C:\pdmm_work2")
ADB = W / "android-sdk" / "platform-tools" / "adb.exe"


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def refresh_tables(outdir):
    """Derive CSV/manifest from case JSON, repairing a partial/truncated CSV."""
    rows = []
    for cid in CASE_IDS:
        try:
            record = load_json(outdir / "cases" / f"{cid}.json")
            if isinstance(record, dict):
                rows.append(record)
        except (OSError, ValueError):
            pass
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_bytes(outdir / "verdicts.csv", stream.getvalue().encode())
    report = evaluate(outdir, require_manifest=False)
    report.update(generated_at=time.time(), verdicts_sha256=digest(outdir / "verdicts.csv"))
    atomic_json(outdir / "completion.json", report)
    return report


class RunLock:
    """Directory-exclusive ownership; verify PID creation time before stale recovery."""
    def __init__(self, outdir):
        self.path = outdir / ".runner.lock"

    def __enter__(self):
        import psutil
        self.identity = {"pid": os.getpid(), "create_time": psutil.Process().create_time()}
        for _ in range(2):
            try:
                with self.path.open("x", encoding="utf-8") as fh:
                    json.dump(self.identity, fh)
                return self
            except FileExistsError:
                prior = load_json(self.path)
                try:
                    active = abs(psutil.Process(prior["pid"]).create_time() - prior["create_time"]) < 0.01
                except psutil.NoSuchProcess:
                    active = False
                if active:
                    raise RuntimeError(f"dynamic runner still active: PID {prior['pid']}")
                self.path.rename(self.path.with_name(".stale-lock-" + uuid.uuid4().hex))
        raise RuntimeError("cannot acquire dynamic run lock")

    def __exit__(self, *args):
        if load_json(self.path) == self.identity:
            self.path.unlink()


class CaseFailure(Exception):
    def __init__(self, message, status="failed", exit_code=1):
        super().__init__(message)
        self.status, self.exit_code = status, exit_code


class Device:
    def __init__(self, serial, timeout_s):
        self.serial, self.deadline = serial, time.monotonic() + timeout_s
        self.commands = []

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CaseFailure("entire case deadline exceeded", "timeout", 124)
        return remaining

    def adb(self, *args, timeout=60, cleanup=False):
        command = [str(ADB), "-s", self.serial, *args]
        limit = timeout if cleanup else min(timeout, self.remaining())
        started = time.time()
        try:
            p = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=limit)
            self.commands.append({"command": command, "started_at": started, "wall_s": time.time() - started,
                                  "exit_code": p.returncode, "stdout": p.stdout, "stderr": p.stderr})
            if p.returncode:
                raise CaseFailure(f"adb exit {p.returncode}: {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}",
                                  "adb_failed", p.returncode)
            return p.stdout
        except subprocess.TimeoutExpired as exc:
            self.commands.append({"command": command, "started_at": started, "wall_s": time.time() - started,
                                  "exit_code": None, "timeout": True})
            raise CaseFailure(f"adb command timed out: {' '.join(args)}", "timeout", 124) from exc

    def shell(self, command, **kwargs):
        return self.adb("shell", command, **kwargs)

    def wait(self, seconds):
        time.sleep(min(seconds, self.remaining()))
        self.remaining()

    def start_activity(self, component):
        out = self.shell(f"am start -W -n {component}")
        status = re.search(r"(?:^|\n)\s*Status:\s*(\S+)", out)
        if re.search(r"(?:^|\n)\s*(?:Error:|Exception)", out) or (status and status.group(1) != "ok"):
            raise CaseFailure(f"activity launch failed: {out}", "launch_failed")


def step(device, log, name, wait=1.5):
    log.append(f"STEP {time.time():.3f} {name}")
    device.shell(f"log -t FBSTEP '{name}'")
    device.wait(wait)


def scenario(device, pkg, log):
    act = pkg + "/.MainActivity"
    step(device, log, "launch", 0)
    device.start_activity(act)
    device.wait(2.5)
    for name, y in (("tap-activity-button", 300), ("tap-fragment-F-button", 920), ("tap-fragment-G-button", 1450)):
        step(device, log, name)
        device.shell(f"input tap 540 {y}")
    step(device, log, "cover-with-settings (onStop)", 0)
    device.shell("am start -a android.settings.SETTINGS")
    device.wait(4)
    step(device, log, "relaunch", 0)
    device.start_activity(act)
    device.wait(3)
    step(device, log, "tap-activity-button-2")
    device.shell("input tap 540 300")
    for name, rotation in (("rotate-landscape", 1), ("rotate-portrait", 0)):
        step(device, log, name, 0)
        device.shell(f"settings put system user_rotation {rotation}")
        device.wait(5)
    step(device, log, "relaunch-on-top (onNewIntent for singleTop)", 0)
    device.start_activity(act)
    device.wait(3)
    step(device, log, "cover-with-settings-2", 0)
    device.shell("am start -a android.settings.SETTINGS")
    device.wait(4)
    step(device, log, "kill-process (state saved)", 0)
    device.shell(f"am kill {pkg}")
    device.wait(3)
    step(device, log, "relaunch-restore", 0)
    device.start_activity(act)
    device.wait(4)
    step(device, log, "tap-activity-button-3")
    device.shell("input tap 540 300")
    step(device, log, "back", 0)
    device.shell("input keyevent 4")
    device.wait(3)


def parse_android_meminfo(text):
    m = (re.search(r"TOTAL PSS:\s*(\d+)", text) or re.search(r"^\s*TOTAL:\s*(\d+)\b", text, re.M)
         or re.search(r"^\s*TOTAL\s+(\d+)\b", text, re.M))
    return int(m.group(1)) * 1024 if m else None


class AndroidAppMonitor:
    """Sample exact-package main processes; PSS/RSS excludes emulator host memory."""
    def __init__(self, serial, pkg, path, interval_s):
        self.serial, self.pkg, self.path, self.interval_s = serial, pkg, path, interval_s
        self.stop = threading.Event()
        self.samples, self.errors = [], {}
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _command(self, command):
        p = subprocess.run([str(ADB), "-s", self.serial, "shell", command], capture_output=True,
                           text=True, errors="replace", timeout=5)
        if p.returncode:
            raise ValueError(f"adb exit {p.returncode}: {command}: {p.stderr.strip()}")
        return p.stdout

    def _loop(self):
        with self.path.open("w", encoding="utf-8") as fh:
            while not self.stop.is_set():
                sample = {"at": time.time(), "pids": [], "pss_bytes": None, "rss_bytes": None}
                try:
                    # pidof exit 1 when app absent is a missing sample, never zero memory.
                    pids = self._command(f"pidof {self.pkg}").split()
                    values = []
                    for pid in pids:
                        if not pid.isdigit():
                            raise ValueError("unexpected pidof output")
                        text = self._command(f"dumpsys meminfo {pid}")
                        if f"[{self.pkg}]" not in text:
                            raise ValueError("Android PID disappeared or was reused")
                        pss, rss = parse_android_meminfo(text), None
                        try:
                            status = self._command(f"cat /proc/{pid}/status")
                            m = re.search(r"^VmRSS:\s*(\d+)\s+kB", status, re.M)
                            rss = int(m.group(1)) * 1024 if m else None
                        except (ValueError, subprocess.TimeoutExpired) as exc:
                            self.errors[str(exc)] = self.errors.get(str(exc), 0) + 1
                        values.append((int(pid), pss, rss))
                    sample["pids"] = [v[0] for v in values]
                    for field, i in (("pss_bytes", 1), ("rss_bytes", 2)):
                        if values and all(v[i] is not None for v in values):
                            sample[field] = sum(v[i] for v in values)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    self.errors[str(exc)] = self.errors.get(str(exc), 0) + 1
                self.samples.append(sample)
                fh.write(json.dumps(sample) + "\n")
                fh.flush()
                self.stop.wait(self.interval_s)

    def start(self):
        self.thread.start()
        return self

    def finish(self):
        self.stop.set()
        self.thread.join()
        result = {"scope": "main Android processes from pidof exact package; excludes colon-named secondary processes and emulator host",
                  "package": self.pkg, "sample_interval_s": self.interval_s,
                  "actual_max_sample_gap_s": max((b["at"] - a["at"] for a, b in zip(self.samples, self.samples[1:])), default=None),
                  "sample_count": len(self.samples), "sampling_errors": self.errors,
                  "pss_basis": "dumpsys meminfo TOTAL PSS/TOTAL; Android kB converted to bytes (1024)",
                  "rss_basis": "/proc/<pid>/status VmRSS; Android kB converted to bytes (1024)",
                  "peak_kind": "maximum sampled simultaneous sum across exact-package main PIDs; not an OS lifetime peak"}
        for name in ("pss", "rss"):
            values = [r[name + "_bytes"] for r in self.samples if r[name + "_bytes"] is not None]
            result["peak_" + name + "_bytes"] = max(values) if values else None
            result[name + "_missing_reason"] = None if values else "no readable samples; app absent or Android access denied"
        return result


def emulator_roots(api):
    import psutil
    matches = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name, argv = (p.info["name"] or "").lower(), p.info["cmdline"] or []
            if ("emulator" in name or "qemu" in name) and "-avd" in argv and argv[argv.index("-avd") + 1] == "api" + api:
                matches.append(p.pid)
        except (psutil.Error, IndexError):
            pass
    return sorted(set(matches))


def trace_window(raw, cid, marker):
    lines = raw.splitlines()
    start = next((i for i, line in enumerate(lines) if "FBSESSION" in line and marker + " START" in line), None)
    end = next((i for i, line in enumerate(lines) if "FBSESSION" in line and marker + " END" in line), None)
    complete = start is not None and end is not None and end > start
    window = lines[start + 1:end if end is not None else len(lines)] if start is not None else []
    kept = [line for line in window if (("FBTRACE" in line or "FBSINK" in line) and re.search(r":\s*" + re.escape(cid) + r"\s", line))
            or "FBSTEP" in line or "AndroidRuntime" in line]
    return kept, complete


def run_case(cid, spec, args, outdir, apkdir, serial):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from resource_monitor import ProcessMonitor
    context = spec["context"]
    pkg = ("fbx" if args.variant == "androidx" else "fb") + "." + cid
    attempt_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    attempt = outdir / "attempts" / cid / attempt_id
    attempt.mkdir(parents=True)
    started, clock = time.time(), time.monotonic()
    record = {"schema": SCHEMA, "id": cid, "api": args.api, "expected": context["case_truth"][cid],
              "apk_sha256": context["apk_sha256"][cid], "context_sha256": spec["context_sha256"],
              "attempt_id": attempt_id, "started_at": started, "ended_at": None, "wall_s": None,
              "seconds": None, "status": "running", "case_exit_code": None,
              "exit_status_basis": "case pipeline exit code; each adb OS return code retained in commands.json; 124 timeout, 130 interruption",
              "sample_interval_s": args.sample_interval, "android_sample_interval_s": args.android_sample_interval,
              "concurrency": args.concurrency, "concurrency_note": "functional run; wall times include concurrent host load",
              "serial": serial, "timestamp_basis": "UTC Unix epoch seconds", "observed": None, "agree": None, "trace_lines": 0,
              "sink_calls": 0, "sink_tainted": 0, "crashed": 0}
    atomic_json(attempt / "record.json", record)
    atomic_json(outdir / "cases" / f"{cid}.json", record)
    refresh_tables(outdir)
    device, log, raw = Device(serial, args.case_timeout), [], ""
    host_monitor = android_monitor = None
    installed = interrupted = False
    host, android = {}, {"peak_pss_bytes": None, "peak_rss_bytes": None, "missing_reason": "application monitor did not start"}
    marker = f"{cid} {attempt_id}"
    try:
        roots = emulator_roots(args.api)
        host_monitor = ProcessMonitor(root_pids={"emulator_host": roots, "runner_host": [os.getpid()]},
                                      sample_interval_s=args.sample_interval).start()
        if not roots:
            raise CaseFailure("cannot identify target API emulator host for resource measurements", "monitor_failed")
        device.adb("reboot")
        device.wait(10)
        device.adb("wait-for-device", timeout=180)
        for _ in range(60):
            if device.shell("getprop sys.boot_completed").strip() == "1":
                break
            device.wait(3)
        else:
            raise CaseFailure("emulator boot not completed", "timeout", 124)
        if device.shell("getprop ro.build.version.sdk").strip() != args.api:
            raise CaseFailure("connected emulator API differs from requested API", "wrong_device")
        device.wait(5)
        device.shell("input keyevent 82")
        # Remove only this case's package to exclude saved state from prior attempts.
        if "package:" + pkg in device.shell("pm list packages " + pkg).splitlines():
            device.adb("uninstall", pkg)
        result = device.adb("install", "-t", str(apkdir / (cid + ".apk")), timeout=120)
        if "Success" not in result:
            raise CaseFailure("install lacked Success confirmation", "install_failed")
        installed = True
        if "package:" + pkg not in device.shell("pm list packages " + pkg).splitlines():
            raise CaseFailure("installed package not found", "install_failed")
        for command in ("settings put system accelerometer_rotation 0", "settings put system user_rotation 0",
                        "settings put global always_finish_activities 0"):
            device.shell(command)
        device.adb("logcat", "-c")
        android_monitor = AndroidAppMonitor(serial, pkg, attempt / "android_samples.jsonl", args.android_sample_interval).start()
        device.shell(f"log -t FBSESSION '{marker} START'")
        scenario_started = time.monotonic()
        try:
            scenario(device, pkg, log)
        finally:
            record["seconds"] = round(time.monotonic() - scenario_started, 6)
        device.shell(f"log -t FBSESSION '{marker} END'")
        raw = device.adb("logcat", "-d", "-v", "time", "-s", "FBTRACE:D", "FBSINK:I", "FBSTEP:I", "FBSESSION:I", "AndroidRuntime:E")
        lines, complete = trace_window(raw, cid, marker)
        sinks = [line for line in lines if "FBSINK" in line]
        record.update(sink_calls=len(sinks), sink_tainted=sum("TAINT#" in line for line in sinks),
                      trace_lines=sum("FBTRACE" in line for line in lines),
                      crashed=int(any("AndroidRuntime" in line and pkg in line for line in lines)))
        if not complete or not record["trace_lines"]:
            raise CaseFailure("trace truncated, missing session boundaries, or no callback trace", "invalid_trace")
        if record["crashed"]:
            raise CaseFailure("Android application crashed", "app_crashed")
        record.update(observed="leak" if record["sink_tainted"] else "noleak", status="completed", case_exit_code=0)
        record["agree"] = int(record["expected"] == record["observed"])
    except KeyboardInterrupt:
        record.update(status="interrupted", case_exit_code=130, error="user interrupted runner")
        interrupted = True
    except Exception as exc:
        record.update(status=getattr(exc, "status", "failed"), case_exit_code=getattr(exc, "exit_code", 1), error=str(exc))
    finally:
        if android_monitor:
            try:
                android = android_monitor.finish()
            except Exception as exc:
                android["missing_reason"] = "Android monitor failed: " + str(exc)
                record["android_measurement_error"] = str(exc)
        else:
            atomic_bytes(attempt / "android_samples.jsonl", b"")
        if not raw:
            try:
                raw = device.adb("logcat", "-d", "-v", "time", "-s", "FBTRACE:D", "FBSINK:I", "FBSTEP:I", "FBSESSION:I", "AndroidRuntime:E",
                                 timeout=10, cleanup=True)
            except Exception as exc:
                record["trace_collection_error"] = str(exc)
        cleanup_errors = []
        if installed:
            for command in (("shell", f"am force-stop {pkg}"), ("uninstall", pkg)):
                try:
                    device.adb(*command, timeout=15, cleanup=True)
                except Exception as exc:
                    cleanup_errors.append(str(exc))
        record["cleanup_errors"] = cleanup_errors
        if cleanup_errors and record["status"] == "completed":
            record.update(status="cleanup_failed", case_exit_code=1)
        if host_monitor:
            try:
                host = host_monitor.finish()
            except Exception as exc:
                host = {"groups": {}, "missing_reason": str(exc)}
                record.update(status="monitor_failed", case_exit_code=1)
        if not host:
            host = {"groups": {}, "missing_reason": "host monitor did not start"}
        for group in ("emulator_host", "runner_host"):
            host.setdefault("groups", {}).setdefault(group, {"peak_tree_sampled_working_set_bytes": None,
                                                              "missing_reason": host.get("missing_reason", "no matched process")})
            record[group + "_peak_tree_working_set_bytes"] = host["groups"][group].get("peak_tree_sampled_working_set_bytes")
        if record["status"] == "completed" and any(record[g + "_peak_tree_working_set_bytes"] is None for g in ("emulator_host", "runner_host")):
            record.update(status="monitor_failed", case_exit_code=1, error="host process memory sampling unavailable")
        record.update(android_app_peak_pss_bytes=android.get("peak_pss_bytes"), android_app_peak_rss_bytes=android.get("peak_rss_bytes"))
        lines, _ = trace_window(raw, cid, marker)
        content = "\n".join([f"# attempt {attempt_id} status={record['status']}", *log, *lines]) + "\n"
        atomic_bytes(attempt / "trace.log", content.encode())
        atomic_bytes(attempt / "raw_logcat.log", raw.encode())
        atomic_json(attempt / "commands.json", device.commands)
        atomic_json(attempt / "resources.json", {"host": host, "android_application": android,
                                                "separate_memory_scopes": "host Windows Working Set and Android app PSS/RSS are independent; never add their peaks",
                                                "host_peak_scope": "CSV host peaks are sampled within this case; OS lifetime peaks in process details can include earlier cases because emulator and runner processes persist"})
        record.update(ended_at=time.time(), wall_s=round(time.monotonic() - clock, 6))
        record["artifacts"] = {key: {"path": str(path.relative_to(outdir)), "sha256": digest(path)}
                               for key, path in (("log", attempt / "trace.log"), ("resources", attempt / "resources.json"),
                                                 ("android_samples", attempt / "android_samples.jsonl"))}
        atomic_json(attempt / "record.json", record)
        atomic_json(outdir / "cases" / f"{cid}.json", record)
        if record["status"] == "completed":
            atomic_bytes(outdir / f"{cid}.log", (attempt / "trace.log").read_bytes())
        refresh_tables(outdir)
    return record, interrupted


def prepare_spec(args, apkdir, srcdir):
    with (srcdir / "cases.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ids = [r["id"] for r in rows]
    if len(ids) != 36 or len(set(ids)) != 36 or set(ids) != set(CASE_IDS):
        raise ValueError("cases.csv must identify exactly the canonical 36 unique cases")
    truth = {r["id"]: r["expect"] for r in rows}
    if any(value not in ("leak", "noleak") for value in truth.values()):
        raise ValueError("unknown dynamic truth label")
    context = {"api": args.api, "variant": args.variant, "expected_case_ids": list(CASE_IDS),
               "case_truth": truth, "apk_sha256": {cid: digest(apkdir / (cid + ".apk")) for cid in CASE_IDS},
               "truth_sha256": digest(srcdir / "cases.csv"), "runner_sha256": digest(__file__),
               "completion_checker_sha256": digest(Path(__file__).with_name("check_dynamic_complete.py")),
               "resource_monitor_sha256": digest(Path(__file__).resolve().parents[1] / "resource_monitor.py"),
               "sample_interval_s": args.sample_interval, "android_sample_interval_s": args.android_sample_interval,
               "case_timeout_s": args.case_timeout, "concurrency": args.concurrency}
    return {"schema": SCHEMA, "context": context, "context_sha256": context_digest(context)}


def select_serial(requested):
    p = subprocess.run([str(ADB), "devices"], capture_output=True, text=True, errors="replace", timeout=15, check=True)
    devices = [line.split()[0] for line in p.stdout.splitlines()[1:] if len(line.split()) >= 2 and line.split()[1] == "device"]
    if requested not in devices or not requested.startswith("emulator-"):
        raise ValueError("requested emulator is not connected")
    return requested


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api")
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--variant", choices=("platform", "androidx"), default=os.environ.get("FB_VARIANT", "platform"))
    parser.add_argument("--run-suffix", default=os.environ.get("FB_RUN_SUFFIX", "_20261008"))
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--android-sample-interval", type=float, default=1.0)
    parser.add_argument("--case-timeout", type=float, default=900)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if (not args.api.isdigit() or not re.fullmatch(r"[A-Za-z0-9_-]*", args.run_suffix)
            or any(not math.isfinite(v) or v <= 0 for v in (args.sample_interval, args.android_sample_interval, args.case_timeout))
            or args.concurrency < 1):
        parser.error("invalid API, suffix, sampling interval, timeout or concurrency")
    ids = args.cases or list(CASE_IDS)
    if len(ids) != len(set(ids)) or not set(ids).issubset(CASE_IDS):
        parser.error("case IDs must be unique members of the canonical 36")
    apkdir = W / "fragbench" / ("apkx" if args.variant == "androidx" else "apk")
    srcdir = W / "fragbench" / ("srcx" if args.variant == "androidx" else "src")
    outdir = (args.outdir or W / "fragbench" / "dyn" / ("api" + args.api + ("x" if args.variant == "androidx" else "") + args.run_suffix)).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    with RunLock(outdir):
        spec = prepare_spec(args, apkdir, srcdir)
        spec_path = outdir / "run_spec.json"
        if spec_path.exists():
            if load_json(spec_path) != spec:
                raise ValueError("configuration/APKs/scripts changed; use fresh suffix to preserve prior attempts")
        elif any(p.name != ".runner.lock" and not p.name.startswith(".stale-lock-") for p in outdir.iterdir()):
            raise ValueError("legacy output found; choose a fresh suffix instead of overwriting it")
        else:
            atomic_json(spec_path, spec)
        refresh_tables(outdir)
        serial, interrupted = None, False
        for cid in ids:
            try:
                prior = load_json(outdir / "cases" / f"{cid}.json")
                if not valid_case(outdir, cid, prior, spec, require_root_log=False):
                    # The attempt is authoritative; reconstruct an interrupted root-log copy.
                    path = outdir / prior["artifacts"]["log"]["path"]
                    atomic_bytes(outdir / f"{cid}.log", path.read_bytes())
                    print(f"{cid}: verified completed attempt {prior['attempt_id']}; skipped", flush=True)
                    continue
                if (isinstance(prior, dict) and prior.get("status") == "running"
                        and re.fullmatch(r"[A-Za-z0-9_-]+", str(prior.get("attempt_id", "")))):
                    attempt = outdir / "attempts" / cid / prior["attempt_id"]
                    atomic_json(attempt / "recovery.json", {"status": "interrupted", "observed_recovery_at": time.time(),
                                "ended_at": None, "wall_s": None, "peak_memory_bytes": None,
                                "missing_reason": "prior runner ended without final persistence; actual end and unsaved host peak are unobserved"})
            except (OSError, ValueError, TypeError, KeyError):
                pass
            serial = serial or select_serial(args.serial)
            result, interrupted = run_case(cid, spec, args, outdir, apkdir, serial)
            print(f"{cid}: {result['status']} expected={result['expected']} observed={result['observed']} wall={result['wall_s']:.3f}s", flush=True)
            if interrupted:
                break
        report = refresh_tables(outdir)
        print(json.dumps(report, indent=2), flush=True)
        return 130 if interrupted else 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

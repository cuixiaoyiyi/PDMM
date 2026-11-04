"""Build a fresh, isolated AndroidX FragBench project and collect exactly 36 APKs.

The input project is copied without caches or old build outputs. Gradle is
launched directly through its Java launcher (no shell pipeline or batch quoting).
Only exit0 plus one new APK for every declared case can produce status=ok.
The staged project, Gradle cache, Java/Android user homes and logs are under
--output. The Android SDK must already contain the project's required packages;
external SDK mutation/download by build plugins is outside this guarantee.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil
import sys

from _common import (atomic_json, clean_success, environment, file_record,
                     jdk_tool, load_helpers, new_output, require_dir,
                     require_file, stamp)


def case_ids(path, expected):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row["id"] for row in rows]
    if len(ids) != expected or len(set(ids)) != expected:
        raise ValueError(f"expected exactly {expected} unique case IDs")
    if any(not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value) for value in ids):
        raise ValueError("unsafe case/module identifier")
    return ids


def collect_apks(project, ids):
    paths = []
    for cid in ids:
        # Exact Gradle debug output directory; never collect an old APK elsewhere.
        candidates = list((Path(project) / cid / "build/outputs/apk/debug").glob("*.apk"))
        if len(candidates) != 1:
            raise ValueError(f"case {cid}: expected one freshly built debug APK, found {len(candidates)}")
        paths.append((cid, candidates[0]))
    return paths


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True, help="generated AndroidX Gradle multi-module project")
    p.add_argument("--gradle-home", required=True, help="unpacked Gradle distribution")
    p.add_argument("--jdk17", required=True)
    p.add_argument("--sdk", required=True)
    p.add_argument("--helpers", required=True)
    p.add_argument("--output", required=True, help="new or empty output root")
    p.add_argument("--expected", type=int, default=36)
    p.add_argument("--timeout", type=float, default=1800)
    args = p.parse_args(argv)
    if args.expected <= 0 or args.timeout <= 0:
        raise ValueError("expected count and timeout must be positive")
    project = require_dir(args.project, "FragBench project")
    gradle = require_dir(args.gradle_home, "Gradle distribution")
    sdk = require_dir(args.sdk, "Android SDK")
    helpers = require_dir(args.helpers, "helpers")
    java = jdk_tool(args.jdk17, "java")
    ids = case_ids(require_file(project / "cases.csv", "case manifest"), args.expected)
    launcher = list((gradle / "lib").glob("gradle-launcher-*.jar"))
    if len(launcher) != 1:
        raise ValueError("expected exactly one Gradle launcher JAR")
    root = new_output(args.output, inputs=[project, gradle, sdk, helpers / "resource_monitor.py"])
    result = {"schema_version": 1, "status": "running", "started_at": stamp(), "arguments": vars(args),
              "case_ids": ids, "case_manifest": file_record(project / "cases.csv"),
              "old_apks_copied": False, "apk_files": []}
    atomic_json(root / "build.json", result)
    try:
        monitor, = load_helpers(helpers, "resource_monitor")
        stage = root / "project"
        shutil.copytree(project, stage, ignore=shutil.ignore_patterns("build", ".gradle", ".git", ".idea", "local.properties", "*.apk", "*.aab"))
        (stage / "local.properties").write_text("sdk.dir=" + sdk.as_posix() + "\n", encoding="utf-8")
        # Use Gradle's normal launcher/agent without cmd.exe or a masking pipe.
        java_home, android_user = root / "java-home", root / "android-user"
        java_home.mkdir()
        android_user.mkdir()
        command = [str(java), "-Xmx64m", "-Xms64m", "-Dorg.gradle.appname=gradle", "-Duser.home=" + str(java_home)]
        agents = list((gradle / "lib/agents").glob("gradle-instrumentation-agent-*.jar"))
        if len(agents) > 1:
            raise ValueError("ambiguous Gradle instrumentation agent")
        if agents:
            command += ["-javaagent:" + str(agents[0])]
        command += ["-classpath", str(launcher[0]), "org.gradle.launcher.GradleMain", "--no-daemon",
                    "--console", "plain", "--stacktrace", "--gradle-user-home", str(root / "gradle-cache"),
                    "--project-dir", str(stage), "-Duser.home=" + str(java_home), "assembleDebug"]
        atomic_json(root / "inputs.json", {"command": command, "java": file_record(java),
                                           "launcher": file_record(launcher[0]),
                                           "agents": [file_record(a) for a in agents],
                                           "input_project": str(project), "build_project": str(stage)})
        with environment({"JAVA_HOME": Path(args.jdk17).resolve(), "ANDROID_HOME": sdk,
                          "ANDROID_SDK_ROOT": sdk, "ANDROID_USER_HOME": android_user,
                          "GRADLE_USER_HOME": root / "gradle-cache"}):
            resource = monitor.run_command(command, cwd=str(root), log_path=str(root / "gradle.log"),
                                           record_path=str(root / "resource.json"), timeout_s=args.timeout,
                                           metadata={"purpose": "fresh benchmark APK build", "concurrency_at_start": 1,
                                                     "max_observed_concurrency": 1, "requested_parallelism": 1}, sample_interval_s=0.5)
        result["resource"] = str(root / "resource.json")
        if not clean_success(resource):
            result["status"] = "failed" if resource.get("cleanup_error") else resource.get("status", "failed")
            return 1
        built = collect_apks(stage, ids)
        target = root / "apks"
        target.mkdir()
        for cid, path in built:
            destination = target / (cid + ".apk")
            shutil.copy2(path, destination)
            result["apk_files"].append({"id": cid, **file_record(destination)})
        result.update(status="ok", collected=len(result["apk_files"]), validated_unique_cases=len(ids))
        print(f"Built and validated {len(ids)} fresh APKs in {target}")
        return 0
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(result["error"], file=sys.stderr)
        return 1
    finally:
        result["ended_at"] = stamp()
        atomic_json(root / "build.json", result)


if __name__ == "__main__":
    raise SystemExit(main())

"""Compile real Gen8/FlowDroid adapters into a new, explicitly chosen directory.

Requires original helper resource_monitor.py (and psutil). --with-probes builds
the real GC-measured Gen8 exporter and Androlic runner; instrumentation is read only.
No Java application analysis is run by this script.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

from _common import (atomic_json, class_records, clean_success, dependency,
                     file_record, jdk_tool, load_helpers, new_output,
                     require_dir, require_file, stamp)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", required=True, help="directory containing rev8/, rev/, shadow/")
    p.add_argument("--deps", required=True, help="directory of version-pinned dependency JARs")
    p.add_argument("--helpers", required=True, help="directory containing original resource_monitor.py")
    p.add_argument("--build-dir", required=True, help="new or empty output root")
    p.add_argument("--backend", choices=["gen8", "taint", "all"], default="all")
    p.add_argument("--jdk8", help="JDK 8 home; required for gen8/all")
    p.add_argument("--jdk17", help="JDK 17 home; required for taint/all")
    p.add_argument("--with-probes", action="store_true", help="also compile measured Gen8 export and Androlic runner")
    p.add_argument("--instrumentation", help="directory containing rev/measure/ExportGcProbe.java")
    p.add_argument("--timeout", type=float, default=180)
    return p


def java_arg(path):
    # javac @argfiles accept quoted paths; use forward slashes on Windows.
    return '"' + Path(path).resolve().as_posix().replace('"', '\\"') + '"'


def measured_gen8(source):
    """The same reviewed source transformation as build_export_probes.py."""
    text = re.sub(r"\bDumpGen8\b", "DumpGen8Measured", source)
    markers = ["long t0 = System.nanoTime();", "double secs = (System.nanoTime() - t0) / 1e9;"]
    if any(text.count(marker) != 1 for marker in markers):
        raise ValueError("DumpGen8 source layout changed; GC transformation requires review")
    text = text.replace(markers[0], "rev.measure.ExportGcProbe probe = rev.measure.ExportGcProbe.start();\n        "
                        + markers[0] + "\n        probe.generationStarted();")
    text = text.replace(markers[1], markers[1] + "\n        probe.generationEnded(secs);")
    end = "System.exit(0);"
    if text.count(end) != 1:
        raise ValueError("DumpGen8 completion marker changed")
    text = text.replace(end, 'probe.finish(new File(outDir, label + "." + cfg + ".gc.metrics.json"), status, '
                        '"OK".equals(status) && failed == 0);\n        ' + end)
    return text


def measured_androlic(source):
    """Byte-identical transformation to original build_androlic_probe.py."""
    text = re.sub(r"\bAndrolic8\b", "Androlic8Measured", source)
    markers = ["LiveSetTracker live = LiveSetTracker.start();", "long t0 = System.nanoTime();",
               "double secs = (System.nanoTime() - t0) / 1e9;",
               'st = "SOLVEFAIL:" + t.getClass().getSimpleName();', "System.exit(0);"]
    if any(text.count(marker) != 1 for marker in markers):
        raise ValueError("original Androlic layout changed; transformation requires review")
    text = text.replace(markers[0], "rev.measure.AndrolicGcProbe probe = rev.measure.AndrolicGcProbe.start();\n        " + markers[0])
    text = text.replace(markers[1], markers[1] + "\n        probe.generationSolveStarted();\n        int measuredSolveFailures = 0;")
    text = text.replace(markers[3], markers[3] + "\n                    measuredSolveFailures++;")
    text = text.replace(markers[2], markers[2] + "\n        probe.generationSolveEnded(secs);")
    text = text.replace(markers[4], 'probe.finish(new File(outCsv + ".gc.metrics.json"), status, "OK".equals(status) && failed == 0 && measuredSolveFailures == 0,\n'
                        '            failed, measuredSolveFailures, lv, label, args[0] + "/" + args[1], rep);\n        ' + markers[4])
    return text


def compile_one(monitor, root, name, javac, sources, jars, timeout):
    target = root / name
    target.mkdir()
    argfile = root / (name + ".sources.txt")
    argfile.write_text("\n".join(java_arg(path) for path in sources) + "\n", encoding="utf-8")
    command = [str(javac), "-J-Xmx512m", "-encoding", "UTF-8", "-nowarn", "-cp",
               os.pathsep.join(str(path) for path in jars), "-d", str(target), "@" + str(argfile)]
    resource = monitor.run_command(command, cwd=str(root), log_path=str(root / (name + ".compile.log")),
                                   record_path=str(root / (name + ".resource.json")), timeout_s=timeout,
                                   metadata={"purpose": "compile source only; no APK experiment", "concurrency_at_start": 1,
                                             "max_observed_concurrency": 1, "requested_parallelism": 1}, sample_interval_s=0.5)
    record = {"name": name, "sources": [file_record(path) for path in sources],
              "jars": [file_record(path) for path in jars], "javac": file_record(javac),
              "classes": class_records(target), "resource": str(root / (name + ".resource.json")),
              "status": "ok" if clean_success(resource) else ("failed" if resource.get("cleanup_error") else resource.get("status", "failed"))}
    if clean_success(resource) and not record["classes"]:
        record["status"] = "invalid_output"
    if record["status"] != "ok":
        raise RuntimeError(f"{name} compilation failed; inspect {root / (name + '.compile.log')}")
    return record


def main(argv=None):
    args = parser().parse_args(argv)
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    src, deps, helpers = (require_dir(value, name) for value, name in
                          [(args.src, "source root"), (args.deps, "dependencies"), (args.helpers, "helpers")])
    gen8 = args.backend in {"gen8", "all"}
    taint = args.backend in {"taint", "all"}
    if gen8 and not args.jdk8 or taint and not args.jdk17:
        raise ValueError("selected backend requires its --jdk8/--jdk17")
    if args.with_probes and (not gen8 or not args.instrumentation):
        raise ValueError("--with-probes requires a Gen8 backend and --instrumentation")
    plan = []
    if gen8:
        sources = sorted((src / "rev/common").rglob("*.java")) + sorted((src / "rev8").rglob("*.java"))
        if not sources:
            raise ValueError("Gen8 Java sources missing")
        jars = [dependency(deps, "DMMPP.jar"), dependency(deps, "Androlic_DMMPP.jar")]
        plan.append(("gen8", jdk_tool(args.jdk8, "javac"), sources, jars))
    if taint:
        sources = sorted((src / "rev").rglob("*.java")) + sorted((src / "shadow").rglob("*.java"))
        if not sources:
            raise ValueError("FlowDroid adapter Java sources missing")
        jars = [dependency(deps, "flowdroid-2.15.1.jar", ("soot-infoflow-cmd-2.15.1-jar-with-dependencies.jar",))]
        plan.append(("taint", jdk_tool(args.jdk17, "javac"), sources, jars))
    inputs = [src, deps, helpers / "resource_monitor.py"] + ([require_dir(args.instrumentation, "instrumentation")] if args.with_probes else [])
    root = new_output(args.build_dir, inputs=inputs)
    result = {"schema_version": 1, "started_at": stamp(), "status": "running", "builds": [],
              "purpose": "portable real-source compilation; no application analysis", "arguments": vars(args)}
    atomic_json(root / "build.json", result)
    try:
        monitor, = load_helpers(helpers, "resource_monitor")
        for name, javac, sources, jars in plan:
            result["builds"].append(compile_one(monitor, root, name, javac, sources, jars, args.timeout))
            atomic_json(root / "build.json", result)
        if args.with_probes:
            generated = root / "generated-src/rev8/DumpGen8Measured.java"
            generated.parent.mkdir(parents=True)
            generated.write_text(measured_gen8((src / "rev8/DumpGen8.java").read_text(encoding="utf-8")), encoding="utf-8")
            probe = require_file(Path(args.instrumentation) / "rev/measure/ExportGcProbe.java", "GC probe")
            jars = [root / "gen8", dependency(deps, "DMMPP.jar")]
            # Directory classpath entries have no file digest; record them separately.
            target = root / "gen8-probe"
            target.mkdir()
            command = [str(jdk_tool(args.jdk8, "javac")), "-J-Xmx512m", "-encoding", "UTF-8", "-cp",
                       os.pathsep.join(map(str, jars)), "-d", str(target), str(generated), str(probe)]
            resource = monitor.run_command(command, cwd=str(root), log_path=str(root / "gen8-probe.compile.log"),
                                           record_path=str(root / "gen8-probe.resource.json"), timeout_s=args.timeout,
                                           metadata={"purpose": "compile GC instrumentation only", "concurrency_at_start": 1,
                                                     "max_observed_concurrency": 1, "requested_parallelism": 1}, sample_interval_s=0.5)
            if not clean_success(resource) or not (target / "rev8/DumpGen8Measured.class").is_file():
                raise RuntimeError("measured Gen8 compilation failed; see gen8-probe.compile.log")
            result["builds"].append({"name": "gen8-probe", "status": "ok", "classes": class_records(target),
                                      "sources": [file_record(generated), file_record(probe)],
                                      "classpath": list(map(str, jars)), "resource": str(root / "gen8-probe.resource.json")})
            cost_source = root / "generated-src/rev8/Androlic8Measured.java"
            cost_source.write_text(measured_androlic((src / "rev8/Androlic8.java").read_text(encoding="utf-8")), encoding="utf-8")
            adapter = require_file(Path(args.instrumentation) / "rev/measure/AndrolicGcProbe.java", "Androlic GC adapter")
            target = root / "cost-probe"
            target.mkdir()
            jars = [root / "gen8", dependency(deps, "DMMPP.jar"), dependency(deps, "Androlic_DMMPP.jar")]
            command = [str(jdk_tool(args.jdk8, "javac")), "-J-Xmx512m", "-encoding", "UTF-8", "-cp",
                       os.pathsep.join(map(str, jars)), "-d", str(target), str(cost_source), str(adapter), str(probe)]
            resource = monitor.run_command(command, cwd=str(root), log_path=str(root / "cost-probe.compile.log"),
                                           record_path=str(root / "cost-probe.resource.json"), timeout_s=args.timeout,
                                           metadata={"purpose": "compile Androlic GC instrumentation only", "concurrency_at_start": 1,
                                                     "max_observed_concurrency": 1, "requested_parallelism": 1}, sample_interval_s=0.5)
            if not clean_success(resource) or not (target / "rev8/Androlic8Measured.class").is_file():
                raise RuntimeError("measured Androlic compilation failed; see cost-probe.compile.log")
            result["builds"].append({"name": "cost-probe", "status": "ok", "classes": class_records(target),
                                      "sources": [file_record(cost_source), file_record(adapter), file_record(probe)],
                                      "classpath": list(map(str, jars)), "resource": str(root / "cost-probe.resource.json")})
        result["status"] = "ok"
        return 0
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        print(result["error"], file=__import__("sys").stderr)
        return 1
    finally:
        result["ended_at"] = stamp()
        atomic_json(root / "build.json", result)


if __name__ == "__main__":
    raise SystemExit(main())

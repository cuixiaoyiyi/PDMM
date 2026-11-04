"""Compile isolated Androlic8Measured without modifying frozen classes or probes."""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from resource_monitor import run_command
from run_static import atomic_json, sha256

def transform(source):
    text = re.sub(r"\bAndrolic8\b", "Androlic8Measured", source)
    markers = ["LiveSetTracker live = LiveSetTracker.start();", "long t0 = System.nanoTime();",
        "double secs = (System.nanoTime() - t0) / 1e9;", "st = \"SOLVEFAIL:\" + t.getClass().getSimpleName();", "System.exit(0);"]
    if any(text.count(marker) != 1 for marker in markers):
        raise ValueError("original Androlic layout changed; transformation requires review")
    text = text.replace(markers[0], "rev.measure.AndrolicGcProbe probe = rev.measure.AndrolicGcProbe.start();\n        " + markers[0])
    text = text.replace(markers[1], markers[1] + "\n        probe.generationSolveStarted();\n        int measuredSolveFailures = 0;")
    text = text.replace(markers[3], markers[3] + "\n                    measuredSolveFailures++;")
    text = text.replace(markers[2], markers[2] + "\n        probe.generationSolveEnded(secs);")
    text = text.replace(markers[4], 'probe.finish(new File(outCsv + ".gc.metrics.json"), status, "OK".equals(status) && failed == 0 && measuredSolveFailures == 0,\n'
        '            failed, measuredSolveFailures, lv, label, args[0] + "/" + args[1], rep);\n        ' + markers[4])
    return text

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-root", default=r"C:\pdmm_work2")
    p.add_argument("--gc-probe-build", default=r"C:\pdmm_work2\build_export_probe8_20261008")
    args = p.parse_args(argv)
    work, gc_build = Path(args.work_root).resolve(), Path(args.gc_probe_build).resolve()
    build = (work / "build_androlic_probe8_20261008").resolve()
    if not build.is_relative_to(work) or build in {work / "build8", work / "build17", gc_build}:
        raise ValueError("isolated build escaped or aliases a frozen build")
    frozen = {str(path): sha256(path) for path in gc_build.rglob("*.class")}
    if not frozen:
        raise ValueError("validated frozen ExportGcProbe build is missing")
    source = HERE / "src/rev8/Androlic8.java"
    original_hash = sha256(source)
    generated = HERE / "work/androlic_probe_sources_20261008/rev8/Androlic8Measured.java"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(transform(source.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    build.mkdir(parents=True, exist_ok=True)
    records = HERE / "work/androlic_probe_build_20261008"
    records.mkdir(parents=True, exist_ok=True)
    files = [generated, HERE / "instrumentation/rev/measure/AndrolicGcProbe.java", HERE / "instrumentation/rev/measure/AndrolicProbeSmoke.java"]
    jdk = Path(r"C:\Program Files\Java\jdk1.8.0_121")
    cp = ";".join(str(path) for path in [gc_build, work / "build8", work / "lib/DMMPP.jar", work / "lib/Androlic_DMMPP.jar"])
    result = run_command([str(jdk / "bin/javac.exe"), "-J-Xmx256m", "-encoding", "UTF-8", "-cp", cp, "-d", str(build)] + [str(path) for path in files],
        cwd=str(HERE), log_path=str(records / "compile.log"), record_path=str(records / "compile.resource.json"), timeout_s=120,
        metadata={"purpose": "isolated infrastructure compilation; no APK experiment"}, sample_interval_s=.25)
    if result["status"] != "ok":
        raise RuntimeError("isolated compile failed: " + str(records / "compile.log"))
    if sha256(source) != original_hash or {str(path): sha256(path) for path in gc_build.rglob("*.class")} != frozen:
        raise RuntimeError("original source or frozen GC probe changed")
    manifest = {"schema_version": 1, "measurement_variant": "androlic_gc_probe_v1", "metric_scope": "Androlic generation+solve",
        "build": str(build), "gc_probe_build": str(gc_build), "java": str(jdk / "bin/java.exe"),
        "original_source": str(source), "original_sha256": original_hash, "generated_source": str(generated), "generated_sha256": sha256(generated),
        "original_csv_and_reported_gc_preserved": True, "frozen_probe_classes_unchanged": frozen,
        "classes": [{"path": str(path), "sha256": sha256(path)} for path in sorted(build.rglob("*.class"))]}
    atomic_json(records / "manifest.json", manifest)
    print(json.dumps({"build": str(build), "gc_probe_build": str(gc_build)}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

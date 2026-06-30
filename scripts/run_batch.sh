#!/usr/bin/env bash
# Batch-run PDMMMain over DroidBench + the real-world APKs shipped with DMMPP.
# Each APK runs in a fresh JVM so Soot global state never leaks between apps.
# NOTE: native Windows java.exe does not understand MSYS "/d/..." paths on the
# classpath, so we cd into the project root and use cwd-relative paths only.
set -u
cd "$(dirname "$0")" || exit 1
J8="/c/Program Files/Java/jdk1.8.0_121"
PLAT="datasets/android-platforms-min"
CP="pdmm/lib_DMMPP.jar;pdmm/build"
OUT="results"
LOG="$OUT/batch.log"

mkdir -p "$OUT"
rm -f "$OUT/rq1_components.csv" "$OUT/rq_app_summary.csv" "$LOG"

run() {  # $1 = apk (relative), $2 = label, $3 = dataset tag
  local apk="$1" label="$2" tag="$3"
  if [ ! -f "$apk" ]; then echo "MISSING $apk" | tee -a "$LOG"; return; fi
  echo ">>> [$tag] $label" >> "$LOG"
  timeout 600 "$J8/bin/java.exe" -Xmx8g -cp "$CP" cn.ac.ios.pdmm.PDMMMain \
      "$PLAT" "$apk" "$OUT" "${tag}:${label}" >>"$LOG" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then echo "    FAILED rc=$rc ($label)" | tee -a "$LOG"; fi
}

echo "===== DroidBench ====="
while IFS= read -r apk; do
  base=$(basename "$apk" .apk)
  cat=$(basename "$(dirname "$apk")")
  run "$apk" "${cat}_${base}" "DroidBench"
done < <(find datasets/DroidBench/apk -name '*.apk' | sort)

echo "===== Real-world: f-Droid ====="
for apk in DMMPP/apks/f-Droid/*.apk; do
  run "$apk" "$(basename "$apk" .apk)" "fDroid"
done

echo "===== Real-world: GooglePlay ====="
for apk in DMMPP/apks/GooglePlay/*.apk; do
  run "$apk" "$(basename "$apk" .apk)" "GooglePlay"
done

echo "===== DONE ====="
echo "components rows: $(($(wc -l < "$OUT/rq1_components.csv") - 1))"
echo "apps rows:       $(($(wc -l < "$OUT/rq_app_summary.csv") - 1))"
echo "failures:        $(grep -c FAILED "$LOG")"

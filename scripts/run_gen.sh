#!/usr/bin/env bash
# Generate parameter-de-bloated instrumented APKs (PDMMGen) for the whole corpus
# and record the *emitted* signature reduction (results/rq1_generated.csv), which
# cross-checks the RQ1 metric against real, JVM-verifiable code.
set -u
cd "$(dirname "$0")" || exit 1
J8="/c/Program Files/Java/jdk1.8.0_121"
PLAT="datasets/android-platforms-min"
CP="pdmm/lib_DMMPP.jar;pdmm/build"
OUTAPK="out_apk"
LOG="results/gen.log"
mkdir -p "$OUTAPK"
rm -f results/rq1_generated.csv "$LOG"

gen() {
  local apk="$1"
  [ -f "$apk" ] || return
  timeout 300 "$J8/bin/java.exe" -Xmx8g -cp "$CP" cn.ac.ios.pdmm.PDMMGenMain \
      "$PLAT" "$apk" "$OUTAPK" >>"$LOG" 2>&1
}

echo "===== DroidBench ====="
while IFS= read -r apk; do gen "$apk"; done < <(find datasets/DroidBench/apk -name '*.apk' | sort)
echo "===== real-world ====="
for apk in DMMPP/apks/f-Droid/*.apk DMMPP/apks/GooglePlay/*.apk; do gen "$apk"; done

echo "DONE"
echo "generated APKs: $(ls "$OUTAPK"/PDMMPP_*.apk 2>/dev/null | wc -l)"
echo "component rows: $(($(wc -l < results/rq1_generated.csv) - 1))"
grep -c "PDMMGen.*reduction" "$LOG"

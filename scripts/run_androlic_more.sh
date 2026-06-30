#!/usr/bin/env bash
# Incremental RQ3 Androlic batch: the remaining (mostly higher-parameter) apps.
# APPENDS to results/rq3_androlic.csv (does not wipe).
set -u
J8="/c/Program Files/Java/jdk1.8.0_121"
CPWIN='C:\pdmm_work\androlic.jar;C:\pdmm_work\build'
OUTWIN='C:\pdmm_work\results\rq3_androlic.csv'
OUT='/c/pdmm_work/results/rq3_androlic.csv'
LOG='/c/pdmm_work/results/androlic_more.log'
CFGDIR='/c/pdmm_work/cfg'
rm -f "$LOG"

write_cfg() {
  {
    echo 'androidPath C:\pdmm_work\platforms'
    echo 'apkBasePath C:\pdmm_work\apks'
    echo "apkName $2"
    echo 'outputBasePath C:\pdmm_work\out'
    echo 'javaHome C:\Program Files\Java\jdk1.8.0_121'
    echo 'maxRunningTime 100000'
    echo 'maxPathNumber 500'
    echo 'maxPathLength 10000'
    echo 'maxContextDepth 4'
    echo 'maxRecursiveInvocationLevel 3'
    echo 'maxLoopUnrollNumber 2'
    echo 'debugMode 0'
    echo 'isJimpleOutput 0'
    echo 'entryMethod DMMPP'
  } > "$CFGDIR/$1.txt"
}

run() {
  local cfgwin="C:\\pdmm_work\\cfg\\$2.txt"
  timeout 420 "$J8/bin/java.exe" -Xmx12g -cp "$CPWIN" cn.ac.ios.pdmm.AndrolicRQ3 \
      "$1" "$cfgwin" "$OUTWIN" "$3" >>"$LOG" 2>&1
  if [ $? -eq 124 ]; then echo "$3,$1,-1,-1,-1,420.00,0.0" >> "$OUT"; fi
}

APPS="xyz.myachin.downloader.apk kick.wpapp.apk appnewnessoflifefellowshiporg.wpapp.apk
f.fajrak.barbatstudio.smartturnv2.apk com.pinayromances.twa.en.apk app.fedilab.openmaps.apk
net.easyjoin.zipnship.apk com.e.ulillgo.apk usd.aleavt.usd.apk com.alb.plusapp.apk"

i=100
for name in $APPS; do
  [ -f "/c/pdmm_work/apks/$name" ] || { echo "MISSING $name" >>"$LOG"; continue; }
  label=$(basename "$name" .apk)
  i=$((i+1)); cfg="m$i"
  write_cfg "$cfg" "$name"
  echo ">>> $label baseline"; run baseline "$cfg" "$label"
  echo ">>> $label ours";     run ours "$cfg" "$label"
done
echo "DONE total rows: $(($(wc -l < "$OUT") - 1))"

"""POST-HOC Holm supplement for the saved68 comparisons, no experiment rerun."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from resource_monitor import run_command

NAME="androlic_real_gc_bg_v2_fast_20261008"
INPUT=HERE / "results/formal_androlic_gc_bg_v2_fast_20261008/paired_signed_rank.csv"
OUTPUT=INPUT.parent / "multiplicity_posthoc_20261009"
ALPHA=Decimal("0.05")
CANDIDATES={"fixed/pertype","fixed/rules","hsm/perarg","hsm/rules"}
UNITS={
    "external_wall_seconds":"seconds", "java_analysis_seconds":"seconds",
    "forced_gc_call_seconds":"seconds", "forced_gc_notification_wait_seconds":"seconds", "forced_gc_total_overhead_seconds":"seconds",
    "forced_gc_after_heap_bytes":"bytes", "generation_solve_peak_after_any_gc_bytes":"bytes",
    "root_working_set_bytes":"bytes", "tree_sampled_working_set_bytes":"bytes",
    "forced_major_gc_confirmed_count":"count", "formals":"count", "symbolic_paths":"count",
    "generation_solve_gc_notification_count":"count", "generation_solve_major_gc_notification_count":"count", "reported_major_gc_count":"count",
    "reported_live_any_mib":"MiB", "reported_live_major_or_final_mib":"MiB",
}

def require(condition, reason):
    if not condition:raise ValueError(reason)

def file_record(path):
    path=Path(path);raw=path.read_bytes();stat=path.stat()
    return {"path":str(path.resolve()),"size":len(raw),"mtime_ns":stat.st_mtime_ns,"sha256":hashlib.sha256(raw).hexdigest()}

def holm(raw):
    """Adjusted p at ordered i = min(1,max_{j<=i}((m-j)*p_sorted[j]))."""
    order=sorted(range(len(raw)),key=lambda i:(raw[i],i));adjusted=[None]*len(raw);running=Decimal(0)
    for rank,index in enumerate(order):
        running=max(running,Decimal(len(raw)-rank)*raw[index])
        adjusted[index]=min(Decimal(1),running)
    return adjusted

def collect():
    require(not OUTPUT.exists(),"immutable posthoc output directory already exists")
    raw=INPUT.read_bytes();stat=INPUT.stat()
    source={"path":str(INPUT.resolve()),"size":len(raw),"mtime_ns":stat.st_mtime_ns,"sha256":hashlib.sha256(raw).hexdigest()}
    require(raw.endswith(b"\n"),"saved paired CSV is truncated")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig"),newline=""));rows=list(reader)
    original_fields=["batch","baseline","candidate","metric","unit","n_pairs","p_two_sided","rank_biserial"]
    require(reader.fieldnames==original_fields and len(rows)==68,"expected saved68-comparison schema")
    identities=[];p_values=[]
    for row in rows:
        require(set(row)==set(original_fields) and all(isinstance(value,str) and value.strip() for value in row.values()),"missing/malformed input value")
        require(row["batch"]==NAME and row["baseline"]=="fixed/perarg" and row["candidate"] in CANDIDATES,"mixed batch/baseline/candidate")
        require(row["metric"] in UNITS and row["unit"]==UNITS[row["metric"]] and row["n_pairs"]=="20","unknown metric/unit or pair count")
        try:p=Decimal(row["p_two_sided"]);rank=Decimal(row["rank_biserial"])
        except InvalidOperation as exc:raise ValueError("malformed numeric input") from exc
        require(p.is_finite() and 0<=p<=1 and rank.is_finite() and -1<=rank<=1,"nonfinite/out-of-range raw p/effect")
        identities.append((row["metric"],row["candidate"]));p_values.append(p)
    require(len(set(identities))==68 and set(identities)=={(metric,candidate) for metric in UNITS for candidate in CANDIDATES},"duplicate or missing family comparison")
    adjusted=holm(p_values)
    require(holm([Decimal(".01"),Decimal(".04"),Decimal(".03")])==[Decimal(".03"),Decimal(".06"),Decimal(".06")],"small ordered/max arithmetic check failed")
    require(holm([Decimal(".02"),Decimal(".02"),Decimal(".3")])==[Decimal(".06"),Decimal(".06"),Decimal(".3")],"tie arithmetic check failed")
    require(all(p<=q<=1 for p,q in zip(p_values,adjusted)),"adjusted p bounds invalid")
    ordered=sorted(range(68),key=lambda i:(p_values[i],i))
    require(all(adjusted[a]<=adjusted[b] for a,b in zip(ordered,ordered[1:])),"step-down monotonicity invalid")
    library={"installed_dependency_used":False,"installation_attempted":False,"fallback":"two small ordered/tied Decimal arithmetic checks and monotonicity/bounds"}
    if importlib.util.find_spec("statsmodels") is not None:
        from statsmodels.stats.multitest import multipletests
        rejected,library_p,_,_=multipletests([float(value) for value in p_values],alpha=float(ALPHA),method="holm")
        require(all(math.isclose(float(value),float(reference),rel_tol=1e-12,abs_tol=1e-15) for value,reference in zip(adjusted,library_p)),"existing statsmodels Holm disagrees")
        require(all(bool(flag)==(value<=ALPHA) for flag,value in zip(rejected,adjusted)),"existing statsmodels Holm decisions disagree")
        library={"installed_dependency_used":True,"library":"statsmodels.stats.multitest.multipletests(method=holm)","installation_attempted":False,"comparison":"all68 adjusted p/decisions agree"}
    generated=[]
    for row,value in zip(rows,adjusted):
        generated.append({**row,"p_holm_fwer":str(value),"alpha":"0.05","holm_reject_at_alpha":"true" if value<=ALPHA else "false",
            "family_size":"68","family_definition":"POST_HOC_all68_saved_comparisons","difference_direction":"candidate_minus_fixed/perarg",
            "positive_rank_biserial":"candidate_metric_larger","measurement_environment":"controlled_background_v2_fast"})
    require(file_record(INPUT)==source,"saved raw paired CSV changed during derivation")
    OUTPUT.mkdir()
    csv_path=OUTPUT / "paired_signed_rank_holm_posthoc.csv"
    with csv_path.open("x",encoding="utf-8",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(generated[0]));writer.writeheader();writer.writerows(generated)
    significant=[row for row in generated if row["holm_reject_at_alpha"]=="true"]
    wall=[row for row in generated if row["metric"]=="external_wall_seconds"]
    summary={"schema_version":1,"created_at":datetime.now(timezone.utc).isoformat(),"analysis_kind":"POST_HOC_multiplicity_supplement_not_preregistered",
        "input":source,"source_script":file_record(__file__),"output_csv":file_record(csv_path),"batch":NAME,"baseline":"fixed/perarg",
        "family":{"size":68,"metrics":sorted(UNITS),"candidates":sorted(CANDIDATES),"definition":"all17 saved available metrics x4 candidate configurations conservatively treated as one family",
            "pre_specified_or_preregistered":False,"chosen_after_raw_results_existed":True,"excluded_missing_metric":"generation_solve_peak_after_major_gc_bytes was missing in all500 prior observations and was not a valid N5 aggregate/comparison; it is not replaced by zero"},
        "holm":{"alpha":"0.05","implementation":"exact Decimal values parsed from original raw p text; stable input-order tie break",
            "algorithm":"sort ascending raw p; multiply ordered zero-based rank j by68-j; apply cumulative maximum and cap at1; map back to original CSV order",
            "formula":"p_adjusted_(i)=min(1,max_{j<=i}((68-j)*p_sorted_(j))) for zero-based j",
            "rejection":"p_holm_fwer <=0.05","checks":library},
        "preserved":{"raw_p_text":True,"original_order":True,"N_pairs":20,"paired_unit":"one APK median of five verified repeats, not100 repetitions as independent pairs",
            "rank_biserial_unit_and_direction":True,"direction":"candidate minus fixed/perarg; positive rank means larger candidate value","no_p_medians_or_ranks_recomputed":True},
        "holm_significant_count":len(significant),"holm_significant_comparisons":significant,"external_wall_comparisons":wall,
        "measurement_environment":"controlled_background_v2_fast","controlled_background":True,"sterile_exclusive":False,"background_load_present":True,"time_load_affected":True,
        "metric_scope":{"OS":"root lifetime Working Set and simultaneous sampled tree Working Set are separate OS metrics",
            "heap":"notification-observed generation+solve after-GC occupancy and confirmed forced-GC final occupancy are different metrics; neither is an absolute JVM live-set peak",
            "legacy":"reported_live_* and reported_major_gc_count preserve unconfirmed legacy tracker outputs and remain separate"},
        "limitations":["POST-HOC family selection is disclosed; this supplement is not a preregistered confirmatory analysis",
            "Holm correction applies to the68 available saved hypotheses and does not correct other families or unreported exploratory analyses",
            "adjustment cannot repair assumptions or validity of the original paired signed-rank p-values; original zero/tie handling and rounding are retained",
            "N_pairs20 counts matched APKs and can include zero differences; it does not mean20 nonzero signed ranks",
            "adjusted nonsignificance does not establish equivalence, no global speedup claim, and metric direction/units must be interpreted individually",
            "bounded background load and observer overhead remain recorded and are not subtracted or reweighted",
            "natural major-GC stage heap peak stays missing, not0; missing hypotheses are not synthesized"],
        "no_Java_WSL_statistical_rerun_500_manifest_or_original_artifact_changes":True}
    with (OUTPUT / "summary.json").open("x",encoding="utf-8",newline="\n") as fh:json.dump(summary,fh,ensure_ascii=False,indent=2);fh.write("\n")
    print(json.dumps({"output":str(OUTPUT),"family":68,"post_hoc":True,"holm_significant_count":len(significant),"external_wall":[{"candidate":r["candidate"],"raw_p":r["p_two_sided"],"holm_p":r["p_holm_fwer"]} for r in wall]}),flush=True)
    return 0

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--collect",action="store_true");args=parser.parse_args()
    if args.collect:return collect()
    log=HERE / "work/posthoc_holm68_20261009.log";resource=HERE / "work/posthoc_holm68_20261009.resource.json"
    require(not OUTPUT.exists() and not log.exists() and not resource.exists(),"new immutable output/log/resource paths required")
    result=run_command([sys.executable,"-X","utf8","-B","work/posthoc_holm68_20261009.py","--collect"],cwd=str(HERE),log_path=log,record_path=resource,timeout_s=None,
        metadata={"scope":"POST_HOC_Holm68_saved_p_only","time_load_affected":True,"measurement_environment":"controlled_background_v2_fast",
            "background_load_present":True,"sterile_exclusive":False,"requested_parallelism":1,"concurrency_at_start":1,"max_observed_concurrency":1})
    print(json.dumps({k:result.get(k) for k in ("status","exit_code","wall_seconds","peak_root_working_set_bytes","peak_tree_sampled_working_set_bytes")}));return result["exit_code"] if result["exit_code"] is not None else 1

if __name__=="__main__":
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError,TypeError,csv.Error) as exc:print(type(exc).__name__+": "+str(exc),file=sys.stderr);raise SystemExit(2)

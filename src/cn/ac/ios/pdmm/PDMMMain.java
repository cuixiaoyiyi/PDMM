package cn.ac.ios.pdmm;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import cn.ac.ios.dmmpp.AndroidCallBacks;
import cn.ac.ios.dmmpp.gen.IInstrumentation;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraph;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphActivity;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphBroadcastReceiver;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphContentProvider;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphFragment;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphService;
import cn.ac.ios.dmmpp.lifecycle.Node;
import soot.ArrayType;
import soot.BooleanType;
import soot.ByteType;
import soot.CharType;
import soot.DoubleType;
import soot.FloatType;
import soot.IntType;
import soot.LongType;
import soot.PackManager;
import soot.PrimType;
import soot.RefType;
import soot.Scene;
import soot.ShortType;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Unit;
import soot.jimple.InvokeExpr;
import soot.jimple.Stmt;
import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointConstants;
import soot.options.Options;
import soot.util.MultiMap;

/**
 * PDMM driver: re-uses the (unmodified) DMMPP front-end to load an APK and build
 * each component's lifecycle graph, then measures
 *   RQ1 - parameter de-bloat (baseline vs conservative vs aggressive)
 *   RQ2 - lifecycle consistency score (FlowDroid vs DMMPP vs Ours)
 * and writes per-component + per-app rows to CSV.
 *
 * Usage:
 *   java cn.ac.ios.pdmm.PDMMMain <android-platforms> <apk> <out-dir> [appLabel]
 */
public class PDMMMain {

    static String platforms, apkPath, outDir, appLabel;

    public static void main(String[] args) {
        platforms = args[0];
        apkPath = args[1];
        outDir = args[2];
        appLabel = args.length > 3 ? args[3] : new File(apkPath).getName();

        initSoot();

        // app-wide facts
        boolean appHasFragment = false;
        for (SootClass sc : Scene.v().getApplicationClasses())
            if (isFragment(sc)) { appHasFragment = true; break; }
        int commitNowCalls = countTransactionCalls("commitNow");
        int commitCalls = countTransactionCalls("commit");
        boolean synchronousSplice = commitNowCalls > 0; // commitNow => synchronous inlining

        // accumulators
        long appBase = 0, appCon = 0, appAgg = 0;
        int nActivity = 0, nFragment = 0, nService = 0, nReceiver = 0, nProvider = 0;
        Set<LcsEvaluator.Edge> fdEdges = new LinkedHashSet<>();
        Set<LcsEvaluator.Edge> dmmppEdges = new LinkedHashSet<>();
        Set<LcsEvaluator.Edge> oursEdges = new LinkedHashSet<>();

        new File(outDir).mkdirs();
        String compCsv = outDir + File.separator + "rq1_components.csv";
        boolean writeHeader = !new File(compCsv).exists();
        try (PrintWriter pw = new PrintWriter(new java.io.FileWriter(compCsv, true))) {
            if (writeHeader)
                pw.println("app,component,kind,baseline_params,conservative_params,aggressive_params,prr_conservative,prr_aggressive,distinct_types");

            Set<SootClass> classes = new HashSet<>(Scene.v().getApplicationClasses());
            for (SootClass component : classes) {
                String kind = null;
                LifecycleGraph graph = null;
                List<String> callbacks = new ArrayList<>();

                if (isActivity(component)) {
                    kind = "Activity";
                    try {
                        Set<SootClass> invoked = AndroidCallBacks.getSootClassesInvoked(component, null, null).mInvokedSootClasses;
                        MultiMap<SootClass, SootMethod> cb = AndroidCallBacks.getCallBackMultiMap(invoked);
                        for (SootClass lc : cb.keySet())
                            for (SootMethod m : cb.get(lc)) callbacks.add(m.getSignature());
                    } catch (Throwable t) { /* keep empty callbacks */ }
                    graph = new LifecycleGraphActivity(callbacks);
                    nActivity++;
                } else if (isFragment(component)) {
                    kind = "Fragment"; graph = new LifecycleGraphFragment(); nFragment++;
                } else if (isService(component)) {
                    kind = "Service"; graph = new LifecycleGraphService(); nService++;
                } else if (isBroadcastReceiver(component)) {
                    kind = "Receiver"; graph = new LifecycleGraphBroadcastReceiver(); nReceiver++;
                } else if (isContentProvider(component)) {
                    kind = "Provider"; graph = new LifecycleGraphContentProvider(); nProvider++;
                } else continue;

                // RQ1: collect parameter slots exactly as DMMGen would, then partition
                List<ParamSlot> slots = collectSlots(component, graph);
                ParamPartitioner.Result pr = ParamPartitioner.partition(slots);
                appBase += pr.baseline; appCon += pr.conservative; appAgg += pr.aggressive;
                pw.printf("%s,%s,%s,%d,%d,%d,%.2f,%.2f,%d%n",
                        csv(appLabel), csv(component.getName()), kind,
                        pr.baseline, pr.conservative, pr.aggressive,
                        pr.prrConservative(), pr.prrAggressive(), pr.baselineByType.size());

                // RQ2: accumulate edges
                if ("Activity".equals(kind)) {
                    fdEdges.addAll(LcsEvaluator.flowDroidEdges(LcsEvaluator.activityMethodList(),
                            appHasFragment ? LcsEvaluator.fragmentMethodList() : Collections.emptyList()));
                    dmmppEdges.addAll(LcsEvaluator.dmmppEdges(graph, LcsEvaluator.Comp.ACT));
                    oursEdges.addAll(LcsEvaluator.hsmEdges(appHasFragment, synchronousSplice));
                } else if ("Fragment".equals(kind)) {
                    dmmppEdges.addAll(LcsEvaluator.dmmppEdges(graph, LcsEvaluator.Comp.FRAG));
                }
            }
        } catch (Exception e) { e.printStackTrace(); }

        LcsEvaluator.Score fd = LcsEvaluator.score(fdEdges);
        LcsEvaluator.Score dm = LcsEvaluator.score(dmmppEdges);
        LcsEvaluator.Score ou = LcsEvaluator.score(oursEdges);

        String appCsv = outDir + File.separator + "rq_app_summary.csv";
        boolean wh2 = !new File(appCsv).exists();
        try (PrintWriter pw = new PrintWriter(new java.io.FileWriter(appCsv, true))) {
            if (wh2)
                pw.println("app,activities,fragments,services,receivers,providers,has_fragment,commit_calls,commitNow_calls,"
                        + "baseline_params,conservative_params,aggressive_params,prr_conservative,prr_aggressive,"
                        + "lcs_flowdroid,lcs_dmmpp,lcs_ours,edges_fd,edges_dmmpp,edges_ours");
            double prrCon = appBase == 0 ? 0 : 100.0 * (appBase - appCon) / appBase;
            double prrAgg = appBase == 0 ? 0 : 100.0 * (appBase - appAgg) / appBase;
            pw.printf("%s,%d,%d,%d,%d,%d,%b,%d,%d,%d,%d,%d,%.2f,%.2f,%.4f,%.4f,%.4f,%d,%d,%d%n",
                    csv(appLabel), nActivity, nFragment, nService, nReceiver, nProvider,
                    appHasFragment, commitCalls, commitNowCalls,
                    appBase, appCon, appAgg, prrCon, prrAgg,
                    fd.lcs(), dm.lcs(), ou.lcs(), fd.total, dm.total, ou.total);
        } catch (Exception e) { e.printStackTrace(); }

        System.out.printf("[PDMM] %s  base=%d con=%d agg=%d  PRR_agg=%.1f%%  LCS fd=%.3f dmmpp=%.3f ours=%.3f%n",
                appLabel, appBase, appCon, appAgg,
                appBase == 0 ? 0 : 100.0 * (appBase - appAgg) / appBase,
                fd.lcs(), dm.lcs(), ou.lcs());
    }

    /* ---------------- parameter slot collection (mirrors DMMGen ctor) -------- */
    static List<ParamSlot> collectSlots(SootClass component, LifecycleGraph graph) {
        List<ParamSlot> slots = new ArrayList<>();
        for (Node node : graph.getNodes()) {
            if (!node.isNopNode()) {
                SootMethod m = IInstrumentation.findMethod(component, node.getMethodSubSig());
                List<Type> ptypes;
                String host;
                if (m != null) { ptypes = m.getParameterTypes(); host = m.getSignature(); }
                else { ptypes = subsigParamTypes(node.getMethodSubSig()); host = component.getName() + ":" + node.getMethodSubSig(); }
                for (Type t : ptypes) slots.add(new ParamSlot(t, host, ParamSlot.Kind.BACKBONE));
            } else if (node.isCallbackNode()) {
                for (String sig : node.getCallbacks()) {
                    SootMethod cb;
                    try { cb = Scene.v().getMethod(sig); } catch (Throwable t) { continue; }
                    SootMethod ctor = getConstructor(cb.getDeclaringClass());
                    if (ctor != null) {
                        for (Type t : ctor.getParameterTypes()) slots.add(new ParamSlot(t, ctor.getSignature(), ParamSlot.Kind.CONSTRUCTOR));
                        for (Type t : cb.getParameterTypes()) slots.add(new ParamSlot(t, cb.getSignature(), ParamSlot.Kind.CALLBACK));
                    }
                }
            }
        }
        return slots;
    }

    static SootMethod getConstructor(SootClass sc) {
        for (SootMethod m : new ArrayList<>(sc.getMethods())) if (m.isConstructor()) return m;
        return null;
    }

    /* ---------------- commit / commitNow detection -------------------------- */
    static int countTransactionCalls(String name) {
        int count = 0;
        for (SootClass sc : new HashSet<>(Scene.v().getApplicationClasses())) {
            for (SootMethod m : new ArrayList<>(sc.getMethods())) {
                if (!m.isConcrete()) continue;
                soot.Body b;
                try { b = m.retrieveActiveBody(); } catch (Throwable t) { continue; }
                for (Unit u : b.getUnits()) {
                    if (!(u instanceof Stmt)) continue;
                    Stmt s = (Stmt) u;
                    if (!s.containsInvokeExpr()) continue;
                    InvokeExpr ie = s.getInvokeExpr();
                    String mn = ie.getMethod().getName();
                    if (!mn.equals(name)) continue;
                    String dc = ie.getMethod().getDeclaringClass().getName();
                    if (dc.contains("FragmentTransaction")) count++;
                }
            }
        }
        return count;
    }

    /* ---------------- component-type detection (mirrors DMMFactory) --------- */
    static boolean isActivity(SootClass c) {
        return sub(c, AndroidEntryPointConstants.ACTIVITYCLASS)
            || sub(c, AndroidEntryPointConstants.APPCOMPATACTIVITYCLASS_V4)
            || sub(c, AndroidEntryPointConstants.APPCOMPATACTIVITYCLASS_V7);
    }
    static boolean isFragment(SootClass c) {
        return sub(c, AndroidEntryPointConstants.FRAGMENTCLASS)
            || sub(c, AndroidEntryPointConstants.SUPPORTFRAGMENTCLASS)
            || sub(c, "androidx.fragment.app.Fragment");
    }
    static boolean isService(SootClass c) { return sub(c, AndroidEntryPointConstants.SERVICECLASS); }
    static boolean isBroadcastReceiver(SootClass c) { return sub(c, AndroidEntryPointConstants.BROADCASTRECEIVERCLASS); }
    static boolean isContentProvider(SootClass c) { return sub(c, AndroidEntryPointConstants.CONTENTPROVIDERCLASS); }

    /** transitive subclass / interface check by class name */
    static boolean sub(SootClass c, String target) {
        if (c == null) return false;
        Set<SootClass> seen = new HashSet<>();
        ArrayList<SootClass> wl = new ArrayList<>();
        wl.add(c);
        while (!wl.isEmpty()) {
            SootClass cur = wl.remove(wl.size() - 1);
            if (cur == null || !seen.add(cur)) continue;
            if (cur.getName().equals(target)) return true;
            if (cur.hasSuperclass()) wl.add(cur.getSuperclassUnsafe());
            for (SootClass it : cur.getInterfaces()) wl.add(it);
        }
        return false;
    }

    /* ---------------- subsig -> param types (fallback) ---------------------- */
    static List<Type> subsigParamTypes(String subsig) {
        List<Type> out = new ArrayList<>();
        int lp = subsig.indexOf('('), rp = subsig.indexOf(')');
        if (lp < 0 || rp < 0 || rp <= lp + 1) return out;
        String inside = subsig.substring(lp + 1, rp).trim();
        if (inside.isEmpty()) return out;
        for (String tk : inside.split(",")) {
            tk = tk.trim();
            int dims = 0;
            while (tk.endsWith("[]")) { dims++; tk = tk.substring(0, tk.length() - 2).trim(); }
            Type base = primType(tk);
            if (base == null) base = RefType.v(tk);
            out.add(dims == 0 ? base : ArrayType.v(base, dims));
        }
        return out;
    }
    static Type primType(String s) {
        switch (s) {
            case "boolean": return BooleanType.v();
            case "byte": return ByteType.v();
            case "char": return CharType.v();
            case "short": return ShortType.v();
            case "int": return IntType.v();
            case "long": return LongType.v();
            case "float": return FloatType.v();
            case "double": return DoubleType.v();
            default: return null;
        }
    }

    static String csv(String s) { return s == null ? "" : s.replace(',', ';'); }

    /* ---------------- Soot init (metrics mode: no APK output) --------------- */
    static void initSoot() {
        soot.G.reset();
        Options.v().set_android_jars(platforms);
        Options.v().set_process_dir(Collections.singletonList(apkPath));
        Options.v().set_no_bodies_for_excluded(true);
        Options.v().set_process_multiple_dex(true);
        Options.v().set_whole_program(true);
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_src_prec(Options.src_prec_apk);
        Options.v().set_allow_phantom_refs(true);
        List<String> excl = new ArrayList<>();
        for (String p : new String[]{"android.*","androidx.*","org.*","soot.*","java.*","sun.*","javax.*","com.sun.*","com.ibm.*","org.xml.*","org.w3c.*","apple.awt.*","com.apple.*","kotlin.*"})
            excl.add(p);
        Options.v().set_exclude(excl);
        soot.Main.v().autoSetOptions();
        Scene.v().loadNecessaryClasses();
        PackManager.v().runPacks();
    }
}

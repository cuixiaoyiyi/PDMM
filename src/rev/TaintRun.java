package rev;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import java.util.HashMap;
import java.util.Map;

import rev.common.DmmEdges;
import rev.common.LiveSetTracker;
import rev.fd.PdmmConfig;
import rev.fd.PdmmSetupApplication;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.jimple.Stmt;
import soot.jimple.infoflow.InfoflowConfiguration;
import soot.jimple.infoflow.android.InfoflowAndroidConfiguration;
import soot.jimple.infoflow.android.SetupApplication;
import soot.jimple.infoflow.methodSummary.data.provider.LazySummaryProvider;
import soot.jimple.infoflow.methodSummary.taintWrappers.SummaryTaintWrapper;
import soot.jimple.infoflow.results.DataFlowResult;
import soot.jimple.infoflow.results.InfoflowPerformanceData;
import soot.jimple.infoflow.results.InfoflowResults;

/**
 * End-to-end taint analysis with FlowDroid 2.15.1 (its command-line defaults:
 * StubDroid summaries as taint wrapper, SPARK call graph) on one APK, with the
 * dummy main configured through the pdmm.* system properties.
 *
 * Usage: java [-Dpdmm.*] rev.TaintRun <platformsDir> <apk> <sourcesSinks> <outDir> <label> <config> [cgAlgo] [timeoutSec]
 * Output in <outDir>:
 *   <label>.<config>.flows.csv  label,config,source_method,source_stmt,sink_method,sink_stmt
 *   <label>.<config>.run.csv    label,config,status,flows,sources,sinks,cg_s,taint_s,path_s,total_s,fd_max_mb,
 *                               wall_s,live_any_mb,live_major_mb,major_gcs,edge_propagations,infoflow_propagations,alias_propagations,
 *                               cg_edges,reachable_methods,dmm_methods,dmm_event_sites,dmm_edges,pdmm
 */
public class TaintRun {

    public static void main(String[] args) throws Exception {
        File platforms = new File(args[0]);
        File apk = new File(args[1]);
        File ss = new File(args[2]);
        File outDir = new File(args[3]);
        String label = args[4];
        String config = args[5];
        String cgAlgo = args.length > 6 ? args[6] : "SPARK";
        int timeout = args.length > 7 ? Integer.parseInt(args[7]) : 0;
        outDir.mkdirs();

        long t0 = System.nanoTime();
        LiveSetTracker live = LiveSetTracker.start();
        String status = "OK";
        int flows = 0, sources = 0, sinks = 0, cgS = 0, taintS = 0, pathS = 0, totalS = 0, fdMem = 0;
        long edgeProp = 0, infoProp = 0, aliasProp = 0, cgEdges = 0, reachable = 0;
        int dmmMethods = 0, dmmSites = 0, dmmEdges = 0;

        try (PrintWriter fw = new PrintWriter(new File(outDir, label + "." + config + ".flows.csv"), "UTF-8")) {
            SetupApplication app = new PdmmSetupApplication(platforms, apk);
            InfoflowAndroidConfiguration cfg = app.getConfig();
            cfg.setCallgraphAlgorithm("CHA".equalsIgnoreCase(cgAlgo)
                    ? InfoflowConfiguration.CallgraphAlgorithm.CHA
                    : InfoflowConfiguration.CallgraphAlgorithm.SPARK);
            if (System.getProperty("pdmm.paths") != null)
                cfg.getPathConfiguration().setPathReconstructionMode(InfoflowConfiguration.PathReconstructionMode.Precise);
            if (timeout > 0) {
                cfg.setDataFlowTimeout(timeout);
                cfg.getPathConfiguration().setPathReconstructionTimeout(timeout);
            }
            // FlowDroid's command-line default is StubDroid alone; pdmm.tw=defaultfallback adds
            // EasyTaintWrapper as fallback for classes without a summary (also a FlowDroid option)
            SummaryTaintWrapper stw = new SummaryTaintWrapper(new LazySummaryProvider("summariesManual"));
            if ("defaultfallback".equals(System.getProperty("pdmm.tw", "default")))
                stw.setFallbackTaintWrapper(soot.jimple.infoflow.taintWrappers.EasyTaintWrapper.getDefault());
            app.setTaintWrapper(stw);

            InfoflowResults res = app.runInfoflow(ss);

            if (res != null) {
                if (res.getResultSet() != null) {
                    List<DataFlowResult> list = new ArrayList<>(res.getResultSet());
                    list.sort(Comparator.comparing(DataFlowResult::toString));
                    for (DataFlowResult r : list) {
                        flows++;
                        if (System.getProperty("pdmm.paths") != null && r.getSource().getPath() != null) {
                            System.out.println("[PATH] sink " + r.getSink().getStmt());
                            for (Stmt ps : r.getSource().getPath())
                                System.out.println("[PATH]    " + methodOf(ps) + " :: " + ps);
                        }
                        fw.println(csv(label, config, methodOf(r.getSource().getStmt()), String.valueOf(r.getSource().getStmt()),
                                methodOf(r.getSink().getStmt()), String.valueOf(r.getSink().getStmt())));
                    }
                }
                InfoflowPerformanceData pd = res.getPerformanceData();
                if (pd != null) {
                    sources = pd.getSourceCount(); sinks = pd.getSinkCount();
                    cgS = pd.getCallgraphConstructionSeconds(); taintS = pd.getTaintPropagationSeconds();
                    pathS = pd.getPathReconstructionSeconds(); totalS = pd.getTotalRuntimeSeconds();
                    fdMem = pd.getMaxMemoryConsumption();
                    edgeProp = pd.getEdgePropagationCount(); infoProp = pd.getInfoflowPropagationCount();
                    aliasProp = pd.getAliasPropagationCount();
                }
                if (res.getTerminationState() != InfoflowResults.TERMINATION_SUCCESS)
                    status = "TERM" + res.getTerminationState();
                if (res.getExceptions() != null && !res.getExceptions().isEmpty())
                    status = (status.equals("OK") ? "OK" : status) + "+EXC";
            }

            // size of the generated entry point and of the call graph
            SootMethod dm = app.getDummyMainMethod();
            if (dm != null) {
                final SootClass dc = dm.getDeclaringClass();
                dmmMethods = dc.getMethods().size();
                Set<SootMethod> roots = new LinkedHashSet<>();
                for (Unit u : dm.getActiveBody().getUnits()) {
                    Stmt s = (Stmt) u;
                    if (s.containsInvokeExpr()) {
                        SootMethod t = s.getInvokeExpr().getMethod();
                        if (t.getDeclaringClass().equals(dc) && t.hasActiveBody())
                            roots.add(t);
                    }
                }
                DmmEdges.Config ec = new DmmEdges.Config() {
                    @Override public boolean isSubDmm(SootMethod m) { return m.getDeclaringClass().equals(dc); }
                    @Override public boolean isIgnored(SootMethod m) {
                        String c = m.getDeclaringClass().getName();
                        return c.equals("ComponentDataExchangeInterface") || c.startsWith("dummyMainClass") || c.equals("PdmmHolder");
                    }
                };
                for (SootMethod root : roots) {
                    DmmEdges.Result r = DmmEdges.extract(root, ec);
                    dmmSites += r.eventCallSites;
                    dmmEdges += r.edges.size();
                }
            }
            if (soot.Scene.v().hasCallGraph()) {
                cgEdges = soot.Scene.v().getCallGraph().size();
                reachable = soot.Scene.v().getReachableMethods().size();
            }
        } catch (Throwable t) {
            status = "ERR:" + t.getClass().getSimpleName() + ":" + String.valueOf(t.getMessage()).replace(',', ';').replace('\n', ' ');
            if (status.length() > 160) status = status.substring(0, 160);
            t.printStackTrace();
        }

        double wall = (System.nanoTime() - t0) / 1e9;
        long[] lv = live.finish();
        try (PrintWriter rw = new PrintWriter(new File(outDir, label + "." + config + ".run.csv"), "UTF-8")) {
            rw.println(csv(label, config, status, s(flows), s(sources), s(sinks), s(cgS), s(taintS), s(pathS), s(totalS), s(fdMem),
                    String.format("%.1f", wall), s(lv[0]), s(lv[1]), s(lv[2]), s(edgeProp), s(infoProp), s(aliasProp), s(cgEdges), s(reachable),
                    s(dmmMethods), s(dmmSites), s(dmmEdges), PdmmConfig.describe().replace(',', ';')));
        }
        System.out.println("[TAINT] " + label + " " + config + " " + status + " flows=" + flows + " cg=" + cgS + "s taint=" + taintS
                + "s wall=" + String.format("%.0f", wall) + "s live=" + lv[0] + "/" + lv[1] + "MB");
        System.exit(0);
    }

    private static Map<Unit, SootMethod> owners = null;

    /** the method whose body contains the statement (built once over all application classes) */
    static String methodOf(Stmt s) {
        if (owners == null) {
            owners = new HashMap<>();
            for (SootClass c : soot.Scene.v().getApplicationClasses())
                for (SootMethod m : c.getMethods())
                    if (m.hasActiveBody())
                        for (Unit u : m.getActiveBody().getUnits())
                            owners.put(u, m);
        }
        SootMethod m = owners.get(s);
        return m == null ? "?" : m.getSignature();
    }

    static String s(long v) { return String.valueOf(v); }

    static String csv(String... f) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < f.length; i++) {
            if (i > 0) sb.append(',');
            String v = f[i] == null ? "" : f[i];
            if (v.indexOf(',') >= 0 || v.indexOf('"') >= 0 || v.indexOf('\n') >= 0) v = '"' + v.replace("\"", "\"\"").replace('\n', ' ') + '"';
            sb.append(v);
        }
        return sb.toString();
    }
}

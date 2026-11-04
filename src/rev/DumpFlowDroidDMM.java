package rev;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import rev.common.DmmEdges;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.jimple.Stmt;
import rev.fd.PdmmSetupApplication;
import soot.jimple.infoflow.android.SetupApplication;

/**
 * Experiments 5 and 2a: dump the dummy main that FlowDroid itself generates for
 * an APK and extract its event-successor relation and event arguments.
 *
 * Usage: java rev.DumpFlowDroidDMM <platformsDir> <apk> <outDir> <label>
 * Output in <outDir>:
 *   <label>.jimple       all generated dummy-main methods
 *   <label>.edges.csv    label,generator,root,from,to,via_new
 *   <label>.args.csv     label,generator,root,event,index,type,form,ctx
 *   <label>.summary.csv  label,generator,status,roots,sub_dmm_calls,event_sites,events,edges,seconds
 */
public class DumpFlowDroidDMM {

    static final String GEN = System.getProperty("pdmm.gen", "flowdroid-2.15.1");

    public static void main(String[] args) throws Exception {
        File platforms = new File(args[0]);
        File apk = new File(args[1]);
        File outDir = new File(args[2]);
        String label = args[3];
        outDir.mkdirs();
        long t0 = System.nanoTime();

        String status = "OK";
        int roots = 0, subCalls = 0, sites = 0, events = 0, edges = 0;
        try (PrintWriter ew = new PrintWriter(new File(outDir, label + ".edges.csv"), "UTF-8");
             PrintWriter aw = new PrintWriter(new File(outDir, label + ".args.csv"), "UTF-8")) {

            SetupApplication app = new PdmmSetupApplication(platforms, apk);
            app.constructCallgraph();

            SootMethod dummyMain = app.getDummyMainMethod();
            if (dummyMain == null)
                throw new IllegalStateException("no dummy main");
            final SootClass dummyClass = dummyMain.getDeclaringClass();

            List<SootMethod> methods = new ArrayList<>(dummyClass.getMethods());
            methods.sort(Comparator.comparing(SootMethod::getSignature));
            try (PrintWriter pw = new PrintWriter(new File(outDir, label + ".jimple"), "UTF-8")) {
                pw.println("// apk: " + apk.getName());
                pw.println("// entry method: " + dummyMain.getSignature());
                for (SootMethod m : methods) {
                    pw.println();
                    pw.println("// ---- " + m.getSignature());
                    pw.println(m.hasActiveBody() ? m.getActiveBody().toString() : "// (no body)");
                }
            }

            // roots: component dummy mains called directly from the entry method
            Set<SootMethod> rootMethods = new LinkedHashSet<>();
            for (Unit u : dummyMain.getActiveBody().getUnits()) {
                Stmt s = (Stmt) u;
                if (s.containsInvokeExpr()) {
                    SootMethod t = s.getInvokeExpr().getMethod();
                    if (t.getDeclaringClass().equals(dummyClass) && t.hasActiveBody())
                        rootMethods.add(t);
                }
            }

            DmmEdges.Config cfg = new DmmEdges.Config() {
                @Override public boolean isSubDmm(SootMethod m) {
                    return m.getDeclaringClass().equals(dummyClass);
                }
                @Override public boolean isIgnored(SootMethod m) {
                    String c = m.getDeclaringClass().getName();
                    return c.equals("ComponentDataExchangeInterface") || c.startsWith("dummyMainClass");
                }
            };

            for (SootMethod root : rootMethods) {
                DmmEdges.Result r = DmmEdges.extract(root, cfg);
                roots++;
                subCalls += r.subDmmCalls;
                sites += r.eventCallSites;
                events += r.events.size();
                edges += r.edges.size();
                String rn = root.getName();
                for (String e : r.edges) {
                    String[] p = e.split(" -> ");
                    ew.println(csv(label, GEN, rn, p[0], p[1], p[2]));
                }
                for (DmmEdges.Arg a : r.args)
                    aw.println(csv(label, GEN, rn, a.eventFull, String.valueOf(a.index), a.declaredType, a.form, a.ctx));
            }
        } catch (Throwable t) {
            status = "ERR:" + t.getClass().getSimpleName() + ":" + String.valueOf(t.getMessage()).replace(',', ';').replace('\n', ' ');
            if (status.length() > 200) status = status.substring(0, 200);
            t.printStackTrace();
        }

        double secs = (System.nanoTime() - t0) / 1e9;
        try (PrintWriter sw = new PrintWriter(new File(outDir, label + ".summary.csv"), "UTF-8")) {
            sw.println(csv(label, GEN, status, String.valueOf(roots), String.valueOf(subCalls), String.valueOf(sites),
                    String.valueOf(events), String.valueOf(edges), String.format("%.2f", secs)));
        }
        System.out.println("[DUMP] " + label + " " + status + " roots=" + roots + " events=" + events + " edges=" + edges);
        System.exit(0);
    }

    static String csv(String... f) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < f.length; i++) {
            if (i > 0) sb.append(',');
            String v = f[i] == null ? "" : f[i];
            if (v.indexOf(',') >= 0 || v.indexOf('"') >= 0) v = '"' + v.replace("\"", "\"\"") + '"';
            sb.append(v);
        }
        return sb.toString();
    }
}

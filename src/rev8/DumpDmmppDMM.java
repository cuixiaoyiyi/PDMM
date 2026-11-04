package rev8;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

import cn.ac.ios.dmmpp.gen.DMMFactory;
import rev.common.DmmEdges;
import rev.common.Kinds;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;

/**
 * Experiments 5 and 2a, DMMPP side: run DMMPP's own generator (DMMFactory, as
 * shipped) on every application class and extract the event-successor relation
 * and the event arguments from the dummy mains it actually produces.
 *
 * Usage: java rev8.DumpDmmppDMM <platformsDir> <apk> <outDir> <label>
 * Output in <outDir>:
 *   <label>.jimple          generated DMMPP methods
 *   <label>.edges.csv       label,generator,root,from,to,via_new
 *   <label>.args.csv        label,generator,root,event,index,type,form,ctx
 *   <label>.components.csv  label,generator,component,kind,status,formal_params,event_sites,events,edges
 *   <label>.summary.csv     label,generator,status,components,generated,failed,formal_params,seconds
 */
public class DumpDmmppDMM {

    static final String GEN = "dmmpp";

    public static void main(String[] args) throws Exception {
        String platforms = args[0], apk = args[1];
        File outDir = new File(args[2]);
        String label = args[3];
        outDir.mkdirs();
        long t0 = System.nanoTime();

        String status = "OK";
        int comps = 0, generated = 0, failed = 0, params = 0;

        DmmEdges.Config cfg = new DmmEdges.Config() {
            @Override public boolean isSubDmm(SootMethod m) { return false; }
            @Override public boolean isIgnored(SootMethod m) { return false; }
        };

        try (PrintWriter ew = new PrintWriter(new File(outDir, label + ".edges.csv"), "UTF-8");
             PrintWriter aw = new PrintWriter(new File(outDir, label + ".args.csv"), "UTF-8");
             PrintWriter cw = new PrintWriter(new File(outDir, label + ".components.csv"), "UTF-8");
             PrintWriter jw = new PrintWriter(new File(outDir, label + ".jimple"), "UTF-8")) {

            SootSetup.load(platforms, apk);

            List<SootClass> classes = new ArrayList<SootClass>(Scene.v().getApplicationClasses());
            Collections.sort(classes, new Comparator<SootClass>() {
                @Override public int compare(SootClass a, SootClass b) { return a.getName().compareTo(b.getName()); }
            });

            for (SootClass c : classes) {
                String kind = Kinds.kindOf(c);
                if ("CB".equals(kind) || "APP".equals(kind)) continue;   // DMMFactory handles the five component kinds
                if (c.isPhantom()) continue;
                comps++;
                String st = "OK";
                int np = 0, sites = 0, events = 0, edges = 0;
                try {
                    SootMethod dmm = DMMFactory.createDDM(c);
                    if (dmm == null) {
                        st = "NULL";
                        failed++;
                    } else {
                        generated++;
                        np = dmm.getParameterCount() - 1;   // last parameter is the boolean[] predicate array
                        params += np;
                        jw.println("// ---- " + dmm.getSignature());
                        jw.println(dmm.getActiveBody().toString());
                        DmmEdges.Result r = DmmEdges.extract(dmm, cfg);
                        sites = r.eventCallSites; events = r.events.size(); edges = r.edges.size();
                        for (String e : r.edges) {
                            String[] p = e.split(" -> ");
                            ew.println(csv(label, GEN, c.getName(), p[0], p[1], p[2]));
                        }
                        for (DmmEdges.Arg a : r.args)
                            aw.println(csv(label, GEN, c.getName(), a.eventFull, String.valueOf(a.index), a.declaredType, a.form, a.ctx));
                    }
                } catch (Throwable t) {
                    failed++;
                    StackTraceElement[] tr = t.getStackTrace();
                    String where = tr.length > 0 ? tr[0].getClassName() + "." + tr[0].getMethodName() + ":" + tr[0].getLineNumber() : "?";
                    st = "ERR:" + t.getClass().getSimpleName() + "@" + where;
                }
                cw.println(csv(label, GEN, c.getName(), kind, st, String.valueOf(np), String.valueOf(sites),
                        String.valueOf(events), String.valueOf(edges)));
            }
        } catch (Throwable t) {
            status = "ERR:" + t.getClass().getSimpleName() + ":" + String.valueOf(t.getMessage()).replace(',', ';').replace('\n', ' ');
            if (status.length() > 200) status = status.substring(0, 200);
            t.printStackTrace();
        }

        double secs = (System.nanoTime() - t0) / 1e9;
        try (PrintWriter sw = new PrintWriter(new File(outDir, label + ".summary.csv"), "UTF-8")) {
            sw.println(csv(label, GEN, status, String.valueOf(comps), String.valueOf(generated), String.valueOf(failed),
                    String.valueOf(params), String.format("%.2f", secs)));
        }
        System.out.println("[DUMP] " + label + " " + status + " comps=" + comps + " generated=" + generated + " failed=" + failed);
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

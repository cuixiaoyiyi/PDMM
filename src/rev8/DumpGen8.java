package rev8;

import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import rev.common.DmmEdges;
import rev.common.Kinds;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;

/**
 * Generates the DMMPP-style dummy mains of one APK with Gen8 under one
 * configuration and records, per component, formal-parameter count, event
 * edges, arguments and the merge log (E1, E2a, RQ1 of the revision).
 *
 * Usage: java rev8.DumpGen8 <platformsDir> <apk> <outDir> <label> <fixed|hsm> <perarg|pertype|rules>
 * Output in <outDir>: <label>.<cfg>.{jimple,edges.csv,args.csv,components.csv,merges.csv,summary.csv}
 */
public class DumpGen8 {

    public static void main(String[] args) throws Exception {
        String platforms = args[0], apk = args[1];
        File outDir = new File(args[2]);
        String label = args[3];
        Gen8.Lifecycle lc = args[4].equals("hsm") ? Gen8.Lifecycle.HSM : Gen8.Lifecycle.DMMPP_FIXED;
        Gen8.Params pm = Gen8.Params.valueOf(args[5].toUpperCase());
        String cfg = args[4] + "_" + args[5];
        String gen = "gen8-" + cfg;
        outDir.mkdirs();
        long t0 = System.nanoTime();

        String status = "OK";
        int comps = 0, generated = 0, failed = 0, params = 0, hosted = 0;

        DmmEdges.Config ec = new DmmEdges.Config() {
            @Override public boolean isSubDmm(SootMethod m) { return false; }
            @Override public boolean isIgnored(SootMethod m) { return false; }
        };

        try (PrintWriter ew = new PrintWriter(new File(outDir, label + "." + cfg + ".edges.csv"), "UTF-8");
             PrintWriter aw = new PrintWriter(new File(outDir, label + "." + cfg + ".args.csv"), "UTF-8");
             PrintWriter cw = new PrintWriter(new File(outDir, label + "." + cfg + ".components.csv"), "UTF-8");
             PrintWriter mw = new PrintWriter(new File(outDir, label + "." + cfg + ".merges.csv"), "UTF-8");
             PrintWriter jw = new PrintWriter(new File(outDir, label + "." + cfg + ".jimple"), "UTF-8")) {

            SootSetup.load(platforms, apk);
            List<SootClass> classes = new ArrayList<SootClass>(Scene.v().getApplicationClasses());
            Collections.sort(classes, new Comparator<SootClass>() {
                @Override public int compare(SootClass a, SootClass b) { return a.getName().compareTo(b.getName()); }
            });

            // hosting relation (only used by HSM)
            Map<SootClass, FragmentHosts.Info> hosts = new LinkedHashMap<SootClass, FragmentHosts.Info>();
            Set<SootClass> hostedFragments = new LinkedHashSet<SootClass>();
            for (SootClass c : classes) {
                if (c.isPhantom() || c.isAbstract() || !Kinds.isActivity(c)) continue;
                FragmentHosts.Info info = FragmentHosts.scan(c);
                hosts.put(c, info);
                if (lc == Gen8.Lifecycle.HSM) hostedFragments.addAll(info.fragments);
            }
            hosted = hostedFragments.size();

            for (SootClass c : classes) {
                String kind = Kinds.kindOf(c);
                if ("CB".equals(kind) || "APP".equals(kind) || c.isPhantom() || c.isAbstract()) continue;
                comps++;
                String st = "OK";
                int np = 0, sites = 0, events = 0, edges = 0;
                try {
                    Gen8.Result r;
                    if ("ACT".equals(kind)) r = Gen8.activity(c, hosts.get(c), lc, pm);
                    else if ("FRAG".equals(kind)) {
                        if (hostedFragments.contains(c)) { st = "SPLICED"; cw.println(csv(label, gen, c.getName(), kind, st, "0", "0", "0", "0")); continue; }
                        r = Gen8.fragment(c, pm);
                    }
                    else if ("SRV".equals(kind)) r = Gen8.service(c, pm);
                    else if ("RCV".equals(kind)) r = Gen8.receiver(c, pm);
                    else r = Gen8.provider(c, pm);
                    generated++;
                    np = r.formals;
                    params += np;
                    jw.println("// ---- " + r.dmm.getSignature());
                    jw.println(r.dmm.getActiveBody().toString());
                    for (String m : r.mergeLog) mw.println(csv(label, gen, m));
                    DmmEdges.Result x = DmmEdges.extract(r.dmm, ec);
                    sites = x.eventCallSites; events = x.events.size(); edges = x.edges.size();
                    for (String e : x.edges) {
                        String[] p = e.split(" -> ");
                        ew.println(csv(label, gen, c.getName(), p[0], p[1], p[2]));
                    }
                    for (DmmEdges.Arg a : x.args)
                        aw.println(csv(label, gen, c.getName(), a.eventFull, String.valueOf(a.index), a.declaredType, a.form, a.ctx));
                } catch (Throwable t) {
                    failed++;
                    if (System.getProperty("pdmm.debug") != null) t.printStackTrace();
                    StackTraceElement[] tr = t.getStackTrace();
                    String where = tr.length > 0 ? tr[0].getClassName() + "." + tr[0].getMethodName() + ":" + tr[0].getLineNumber() : "?";
                    st = "ERR:" + t.getClass().getSimpleName() + "@" + where;
                }
                cw.println(csv(label, gen, c.getName(), kind, st, String.valueOf(np), String.valueOf(sites), String.valueOf(events), String.valueOf(edges)));
            }
        } catch (Throwable t) {
            status = "ERR:" + t.getClass().getSimpleName() + ":" + String.valueOf(t.getMessage()).replace(',', ';').replace('\n', ' ');
            if (status.length() > 200) status = status.substring(0, 200);
            t.printStackTrace();
        }
        double secs = (System.nanoTime() - t0) / 1e9;
        try (PrintWriter sw = new PrintWriter(new File(outDir, label + "." + cfg + ".summary.csv"), "UTF-8")) {
            sw.println(csv(label, gen, status, String.valueOf(comps), String.valueOf(generated), String.valueOf(failed),
                    String.valueOf(params), String.format("%.2f", secs), String.valueOf(hosted)));
        }
        System.out.println("[DUMP] " + label + " " + gen + " " + status + " comps=" + comps + " generated=" + generated
                + " failed=" + failed + " formals=" + params + " hostedFragments=" + hosted);
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

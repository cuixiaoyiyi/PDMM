package rev8;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import cn.ac.ios.dmmpp.AndroidCallBacks;
import rev.common.Kinds;
import soot.Body;
import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Unit;
import soot.Value;
import soot.jimple.AssignStmt;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.InvokeExpr;
import soot.jimple.NewExpr;
import soot.jimple.Stmt;

/**
 * Which fragments an activity hosts (DMMPP side). Sources of evidence:
 *   - FragmentTransaction.add/replace/attach/show and DialogFragment.show call
 *     sites in methods of the classes reachable from the activity (DMMPP's own
 *     reachability, AndroidCallBacks.getSootClassesInvoked), fragment class
 *     resolved from the argument's declared type or the allocation in the method;
 *   - fragments declared in the layout files the activity inflates (DMMPP's
 *     layout parser).
 * Per fragment it also records whether every transaction site lies in an
 * activity's onCreate and whether a synchronous commit occurs.
 */
public final class FragmentHosts {

    private FragmentHosts() {}

    private static final Set<String> TX_CLASSES = new HashSet<String>(Arrays.asList(
            "android.app.FragmentTransaction", "android.support.v4.app.FragmentTransaction",
            "androidx.fragment.app.FragmentTransaction"));
    private static final Set<String> ADD_OPS = new HashSet<String>(Arrays.asList("add", "replace", "attach", "show"));
    private static final Set<String> SYNC = new HashSet<String>(Arrays.asList("commitNow", "commitNowAllowingStateLoss",
            "executePendingTransactions", "showNow"));

    public static final class Info {
        public final Set<SootClass> fragments = new LinkedHashSet<SootClass>();
        public final Set<SootClass> onCreateOnly = new LinkedHashSet<SootClass>();
        public final Set<SootClass> sync = new LinkedHashSet<SootClass>();
        public final Set<SootClass> fromXml = new LinkedHashSet<SootClass>();
        public final List<String> callbacks = new ArrayList<String>();
        public int txSites = 0;
    }

    public static Info scan(SootClass activity) {
        Info info = new Info();
        Set<SootClass> reach;
        Set<String> layouts = null;
        try {
            AndroidCallBacks.ActivityInfo ai = AndroidCallBacks.getSootClassesInvoked(activity, null, null);
            reach = ai.mInvokedSootClasses;
            layouts = ai.mInvokedLayoutXmls;
            for (SootClass lc : AndroidCallBacks.getCallBackMultiMap(reach).keySet())
                for (SootMethod m : AndroidCallBacks.getCallBackMultiMap(reach).get(lc))
                    info.callbacks.add(m.getSignature());
        } catch (Throwable t) {
            reach = new HashSet<SootClass>();
            reach.add(activity);
        }
        // layout-declared fragments
        if (layouts != null && AndroidCallBacks.sXMLFRAGMENTS != null) {
            for (String l : layouts)
                for (SootClass f : AndroidCallBacks.sXMLFRAGMENTS.get(l))
                    if (f.isApplicationClass() && Kinds.isFragment(f)) {
                        info.fragments.add(f);
                        info.fromXml.add(f);
                    }
        }
        // transaction sites
        Map<SootClass, Set<String>> sites = new LinkedHashMap<SootClass, Set<String>>();
        for (SootClass c : reach) {
            if (!c.isApplicationClass() || c.isPhantom())
                continue;
            if (Kinds.isActivity(c) && c != activity)
                continue;   // another activity's transactions belong to that activity
            for (SootMethod m : new ArrayList<SootMethod>(c.getMethods())) {
                if (!m.isConcrete())
                    continue;
                Body b;
                try { b = m.retrieveActiveBody(); } catch (RuntimeException e) { continue; }
                List<SootClass> here = new ArrayList<SootClass>();
                for (Unit u : b.getUnits()) {
                    Stmt s = (Stmt) u;
                    if (!s.containsInvokeExpr())
                        continue;
                    InvokeExpr ie = s.getInvokeExpr();
                    SootMethod callee;
                    try { callee = ie.getMethod(); } catch (RuntimeException e) { continue; }
                    String cls = callee.getDeclaringClass().getName();
                    String name = callee.getName();
                    if (TX_CLASSES.contains(cls) && ADD_OPS.contains(name)) {
                        for (int i = 0; i < ie.getArgCount(); i++) {
                            Value a = ie.getArg(i);
                            if (a instanceof Local && a.getType() instanceof RefType) {
                                SootClass fc = resolve((Local) a, b, u);
                                if (fc != null) { here.add(fc); record(sites, fc, m, activity); info.txSites++; }
                            }
                        }
                    } else if (name.equals("show") && ie instanceof InstanceInvokeExpr && isDialogFragment(callee.getDeclaringClass())) {
                        Value base = ((InstanceInvokeExpr) ie).getBase();
                        if (base instanceof Local) {
                            SootClass fc = resolve((Local) base, b, u);
                            if (fc != null) { here.add(fc); record(sites, fc, m, activity); info.txSites++; }
                        }
                    } else if (SYNC.contains(name)) {
                        info.sync.addAll(here);
                    }
                }
            }
        }
        for (Map.Entry<SootClass, Set<String>> e : sites.entrySet()) {
            info.fragments.add(e.getKey());
            if (e.getValue().size() == 1 && e.getValue().contains("onCreate") && !info.fromXml.contains(e.getKey()))
                info.onCreateOnly.add(e.getKey());
        }
        for (SootClass f : info.fromXml)
            if (!sites.containsKey(f))
                info.onCreateOnly.add(f);
        return info;
    }

    private static void record(Map<SootClass, Set<String>> sites, SootClass fc, SootMethod m, SootClass activity) {
        Set<String> s = sites.get(fc);
        if (s == null) { s = new HashSet<String>(); sites.put(fc, s); }
        boolean inOnCreate = m.getName().equals("onCreate") && m.getDeclaringClass() == activity;
        s.add(inOnCreate ? "onCreate" : m.getSignature());
    }

    private static boolean isDialogFragment(SootClass d) {
        return Kinds.isSub(d, "android.app.DialogFragment") || Kinds.isSub(d, "androidx.fragment.app.DialogFragment")
                || Kinds.isSub(d, "android.support.v4.app.DialogFragment");
    }

    static SootClass resolve(Local l, Body b, Unit use) {
        SootClass declared = ((RefType) l.getType()).getSootClass();
        SootClass best = declared.isApplicationClass() && !declared.isAbstract() && Kinds.isFragment(declared) ? declared : null;
        for (Unit u : b.getUnits()) {
            if (u == use)
                break;
            if (u instanceof AssignStmt && ((AssignStmt) u).getLeftOp() == l) {
                Value r = ((AssignStmt) u).getRightOp();
                SootClass rc = null;
                if (r instanceof NewExpr)
                    rc = ((NewExpr) r).getBaseType().getSootClass();
                else if (r.getType() instanceof RefType)
                    rc = ((RefType) r.getType()).getSootClass();
                if (rc != null && rc.isApplicationClass() && !rc.isAbstract() && Kinds.isFragment(rc))
                    best = rc;
            }
        }
        return best;
    }

    /** every application fragment class */
    public static Set<SootClass> allFragments() {
        Set<SootClass> s = new LinkedHashSet<SootClass>();
        for (SootClass c : Scene.v().getApplicationClasses())
            if (!c.isPhantom() && !c.isAbstract() && Kinds.isFragment(c))
                s.add(c);
        return s;
    }
}

package rev.fd;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import rev.common.Kinds;
import soot.Body;
import soot.Local;
import soot.Modifier;
import soot.PatchingChain;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Unit;
import soot.Value;
import soot.VoidType;
import soot.jimple.AssignStmt;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.InvokeExpr;
import soot.jimple.Jimple;
import soot.jimple.JimpleBody;
import soot.jimple.NewExpr;
import soot.jimple.Stmt;
import soot.jimple.infoflow.entryPointCreators.SimulatedCodeElementTag;

/**
 * Transaction-site instrumentation (pdmm.txsite=1).
 *
 * The framework runs the lifecycle of the very fragment object that the app
 * hands to FragmentTransaction.add/replace/attach/show (or DialogFragment.show).
 * FlowDroid's dummy main instead allocates a fresh instance, so state the app put
 * into the object before the transaction never reaches the lifecycle callbacks.
 *
 * This pass inserts, after every such call, a store of the fragment object into
 * a static field of PdmmHolder; the CREATE phase of the fragment reads it back.
 * After commitNow(), commitNowAllowingStateLoss() and executePendingTransactions()
 * it inserts a call to a stub that runs the fragment's phases synchronously at
 * the call site (filled by the host's ActivityEntryPointCreator).
 *
 * It also records, per fragment class, whether all its transaction sites lie in
 * an activity's onCreate.
 */
public final class TxSiteInstrumenter {

    private TxSiteInstrumenter() {}

    private static final Set<String> TX_CLASSES = new HashSet<String>(Arrays.asList(
            "android.app.FragmentTransaction", "android.support.v4.app.FragmentTransaction",
            "androidx.fragment.app.FragmentTransaction"));
    private static final Set<String> FM_CLASSES = new HashSet<String>(Arrays.asList(
            "android.app.FragmentManager", "android.support.v4.app.FragmentManager",
            "androidx.fragment.app.FragmentManager"));
    private static final Set<String> ADD_OPS = new HashSet<String>(Arrays.asList("add", "replace", "attach", "show"));
    private static final Set<String> SYNC_COMMITS = new HashSet<String>(Arrays.asList(
            "commitNow", "commitNowAllowingStateLoss"));
    private static final Set<String> CREATED_STAGE_METHODS = new HashSet<String>(Arrays.asList(
            "onCreate", "onStart", "onRestoreInstanceState", "onPostCreate", "onAttach", "onActivityCreated",
            "onCreateView", "onViewCreated", "onViewStateRestored", "<init>"));

    private static int lastSceneHash = 0;

    /** statistics of the last run, for the experiment log */
    public static int captureSites = 0, syncSites = 0, unresolvedSites = 0;

    public static void run() {
        int h = System.identityHashCode(Scene.v());
        if (h == lastSceneHash)
            return;
        lastSceneHash = h;
        captureSites = syncSites = unresolvedSites = 0;
        PdmmRegistry.syncStubCreated.clear();
        PdmmRegistry.syncStubResumed.clear();
        Map<SootClass, Set<String>> sites = new LinkedHashMap<SootClass, Set<String>>();

        for (SootClass c : new ArrayList<SootClass>(Scene.v().getApplicationClasses())) {
            if (c.isPhantom() || c.getName().equals(PdmmRegistry.HOLDER))
                continue;
            for (SootMethod m : new ArrayList<SootMethod>(c.getMethods())) {
                if (!m.isConcrete())
                    continue;
                Body b;
                try { b = m.retrieveActiveBody(); } catch (RuntimeException e) { continue; }
                instrument(c, m, b, sites);
            }
        }
        for (Map.Entry<SootClass, Set<String>> e : sites.entrySet()) {
            boolean allOnCreate = true;
            for (String s : e.getValue())
                if (!s.equals("onCreate"))
                    allOnCreate = false;
            if (allOnCreate)
                PdmmRegistry.onCreateOnlyFragments.add(e.getKey());
            else
                PdmmRegistry.dynamicFragments.add(e.getKey());
        }
        System.out.println("[pdmm] txsite: capture sites=" + captureSites + " sync sites=" + syncSites
                + " unresolved=" + unresolvedSites + " fragments=" + sites.size()
                + " onCreateOnly=" + PdmmRegistry.onCreateOnlyFragments.size());
    }

    private static void instrument(SootClass c, SootMethod m, Body b, Map<SootClass, Set<String>> sites) {
        Jimple j = Jimple.v();
        PatchingChain<Unit> units = b.getUnits();
        List<Object[]> capturedHere = new ArrayList<Object[]>();   // {SootClass, Local}
        for (Unit u : new ArrayList<Unit>(units)) {
            Stmt s = (Stmt) u;
            if (!s.containsInvokeExpr())
                continue;
            InvokeExpr ie = s.getInvokeExpr();
            SootMethod callee;
            try { callee = ie.getMethod(); } catch (RuntimeException e) { continue; }
            String cls = callee.getDeclaringClass().getName();
            String name = callee.getName();

            if (TX_CLASSES.contains(cls) && ADD_OPS.contains(name)) {
                // the fragment argument
                for (int i = 0; i < ie.getArgCount(); i++) {
                    Value a = ie.getArg(i);
                    if (!(a instanceof Local) || !(a.getType() instanceof RefType))
                        continue;
                    SootClass fc = resolveFragmentClass((Local) a, b, u);
                    if (fc == null) {
                        if (Kinds.isFragment(((RefType) a.getType()).getSootClass()))
                            unresolvedSites++;
                        continue;
                    }
                    Stmt store = j.newAssignStmt(j.newStaticFieldRef(PdmmRegistry.fragmentField(fc).makeRef()), a);
                    store.addTag(SimulatedCodeElementTag.TAG);
                    units.insertAfter(store, u);
                    captureSites++;
                    capturedHere.add(new Object[] { fc, a });
                    record(sites, fc, m);
                }
            } else if (ie instanceof InstanceInvokeExpr && name.equals("show") && isDialogFragmentShow(callee)) {
                Value base = ((InstanceInvokeExpr) ie).getBase();
                if (base instanceof Local) {
                    SootClass fc = resolveFragmentClass((Local) base, b, u);
                    if (fc != null) {
                        Stmt store = j.newAssignStmt(j.newStaticFieldRef(PdmmRegistry.fragmentField(fc).makeRef()), base);
                        store.addTag(SimulatedCodeElementTag.TAG);
                        units.insertAfter(store, u);
                        captureSites++;
                        capturedHere.add(new Object[] { fc, base });
                        record(sites, fc, m);
                    }
                }
            } else if ((TX_CLASSES.contains(cls) && SYNC_COMMITS.contains(name))
                    || (FM_CLASSES.contains(cls) && name.equals("executePendingTransactions"))) {
                if (capturedHere.isEmpty())
                    continue;
                Local host = hostLocal(c, b, u);
                if (System.getProperty("pdmm.debug") != null)
                    System.err.println("[pdmm] sync site in " + m.getSignature() + " host=" + host + " captured=" + capturedHere.size());
                if (host == null)
                    continue;
                boolean created = CREATED_STAGE_METHODS.contains(m.getName());
                Unit after = u;
                Set<SootClass> seen = new HashSet<SootClass>();
                for (Object[] cap : capturedHere) {
                    SootClass fc = (SootClass) cap[0];
                    if (!seen.add(fc))
                        continue;
                    PdmmRegistry.syncFragments.add(fc);
                    SootMethod stub = stub(fc, created);
                    // the fragment object itself is passed, so that taints written by its
                    // callbacks map back onto the caller's local through the ordinary
                    // call-return mapping (no static-field alias analysis needed)
                    Stmt call = j.newInvokeStmt(j.newStaticInvokeExpr(stub.makeRef(), Arrays.<Value>asList(host, (Value) cap[1])));
                    call.addTag(SimulatedCodeElementTag.TAG);
                    units.insertAfter(call, after);
                    after = call;
                    syncSites++;
                }
            }
        }
    }

    private static void record(Map<SootClass, Set<String>> sites, SootClass fc, SootMethod m) {
        Set<String> s = sites.get(fc);
        if (s == null) {
            s = new HashSet<String>();
            sites.put(fc, s);
        }
        boolean inActivityOnCreate = m.getName().equals("onCreate") && Kinds.isActivity(m.getDeclaringClass());
        s.add(inActivityOnCreate ? "onCreate" : m.getDeclaringClass().getName() + "." + m.getName());
    }

    private static boolean isDialogFragmentShow(SootMethod callee) {
        SootClass d = callee.getDeclaringClass();
        return Kinds.isSub(d, "android.app.DialogFragment") || Kinds.isSub(d, "androidx.fragment.app.DialogFragment")
                || Kinds.isSub(d, "android.support.v4.app.DialogFragment");
    }

    /**
     * The fragment class of a local: its declared type when that is a concrete app
     * fragment class, otherwise the class allocated into the local earlier in the
     * method (the last `new` before the use).
     */
    private static SootClass resolveFragmentClass(Local l, Body b, Unit use) {
        SootClass declared = ((RefType) l.getType()).getSootClass();
        SootClass best = declared.isApplicationClass() && !declared.isAbstract() && Kinds.isFragment(declared) ? declared : null;
        for (Unit u : b.getUnits()) {
            if (u == use)
                break;
            if (u instanceof AssignStmt && ((AssignStmt) u).getLeftOp() == l) {
                Value r = ((AssignStmt) u).getRightOp();
                if (r instanceof NewExpr) {
                    SootClass nc = ((NewExpr) r).getBaseType().getSootClass();
                    if (nc.isApplicationClass() && Kinds.isFragment(nc))
                        best = nc;
                } else if (r instanceof Local && ((Local) r).getType() instanceof RefType) {
                    SootClass rc = ((RefType) ((Local) r).getType()).getSootClass();
                    if (rc.isApplicationClass() && !rc.isAbstract() && Kinds.isFragment(rc))
                        best = rc;
                } else if (r instanceof InvokeExpr && r.getType() instanceof RefType) {
                    SootClass rc = ((RefType) r.getType()).getSootClass();
                    if (rc.isApplicationClass() && !rc.isAbstract() && Kinds.isFragment(rc))
                        best = rc;
                }
            }
        }
        return best;
    }

    /** a local holding the host activity at the given point: `this` in an activity, getActivity() in a fragment */
    private static Local hostLocal(SootClass c, Body b, Unit at) {
        if (m_isStatic(b))
            return null;
        if (Kinds.isActivity(c))
            return b.getThisLocal();
        if (Kinds.isFragment(c)) {
            SootMethod ga = findGetActivity(c);
            if (ga == null)
                return null;
            Jimple j = Jimple.v();
            Local host = j.newLocal("pdmm_host" + b.getLocalCount(), RefType.v("android.app.Activity"));
            b.getLocals().add(host);
            Stmt s = j.newAssignStmt(host, j.newVirtualInvokeExpr(b.getThisLocal(), ga.makeRef()));
            s.addTag(SimulatedCodeElementTag.TAG);
            b.getUnits().insertBefore(s, at);
            return host;
        }
        // an inner class (listener, adapter) that holds its enclosing activity or fragment
        for (soot.SootField fld : c.getFields()) {
            if (!(fld.getType() instanceof RefType) || fld.isStatic())
                continue;
            SootClass ft = ((RefType) fld.getType()).getSootClass();
            if (Kinds.isActivity(ft)) {
                Jimple j = Jimple.v();
                Local host = j.newLocal("pdmm_host" + b.getLocalCount(), fld.getType());
                b.getLocals().add(host);
                Stmt s = j.newAssignStmt(host, j.newInstanceFieldRef(b.getThisLocal(), fld.makeRef()));
                s.addTag(SimulatedCodeElementTag.TAG);
                b.getUnits().insertBefore(s, at);
                return host;
            }
        }
        for (soot.SootField fld : c.getFields()) {
            if (!(fld.getType() instanceof RefType) || fld.isStatic())
                continue;
            SootClass ft = ((RefType) fld.getType()).getSootClass();
            if (Kinds.isFragment(ft)) {
                SootMethod ga = findGetActivity(ft);
                if (ga == null)
                    continue;
                Jimple j = Jimple.v();
                Local outer = j.newLocal("pdmm_outer" + b.getLocalCount(), fld.getType());
                Local host = j.newLocal("pdmm_host" + b.getLocalCount(), RefType.v("android.app.Activity"));
                b.getLocals().add(outer);
                b.getLocals().add(host);
                Stmt s1 = j.newAssignStmt(outer, j.newInstanceFieldRef(b.getThisLocal(), fld.makeRef()));
                Stmt s2 = j.newAssignStmt(host, j.newVirtualInvokeExpr(outer, ga.makeRef()));
                s1.addTag(SimulatedCodeElementTag.TAG);
                s2.addTag(SimulatedCodeElementTag.TAG);
                b.getUnits().insertBefore(s1, at);
                b.getUnits().insertBefore(s2, at);
                return host;
            }
        }
        return null;
    }

    private static boolean m_isStatic(Body b) {
        return b.getMethod().isStatic();
    }

    private static SootMethod findGetActivity(SootClass c) {
        for (SootClass k = c; k != null; k = k.hasSuperclass() ? k.getSuperclass() : null) {
            SootMethod m = k.getMethodUnsafe("android.app.Activity getActivity()");
            if (m != null)
                return m;
            m = k.getMethodUnsafe("androidx.fragment.app.FragmentActivity getActivity()");
            if (m != null)
                return m;
            m = k.getMethodUnsafe("android.support.v4.app.FragmentActivity getActivity()");
            if (m != null)
                return m;
        }
        return null;
    }

    /** empty static method PdmmHolder.sync_<created|resumed>_<F>(Activity, F), filled later */
    private static SootMethod stub(SootClass fc, boolean created) {
        Map<SootClass, SootMethod> reg = created ? PdmmRegistry.syncStubCreated : PdmmRegistry.syncStubResumed;
        SootMethod sm = reg.get(fc);
        if (sm != null)
            return sm;
        SootClass h = PdmmRegistry.holder();
        String name = "sync_" + (created ? "created_" : "resumed_") + PdmmRegistry.mangle(fc);
        sm = h.getMethodByNameUnsafe(name);
        if (sm == null) {
            List<Type> params = new ArrayList<Type>();
            params.add(RefType.v("android.app.Activity"));
            params.add(fc.getType());
            sm = Scene.v().makeSootMethod(name, params, VoidType.v(), Modifier.PUBLIC | Modifier.STATIC);
            h.addMethod(sm);
            sm.addTag(SimulatedCodeElementTag.TAG);
            JimpleBody body = Jimple.v().newBody(sm);
            sm.setActiveBody(body);
            body.insertIdentityStmts();
            body.getUnits().add(Jimple.v().newReturnVoidStmt());
        }
        reg.put(fc, sm);
        return sm;
    }
}

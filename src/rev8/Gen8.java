package rev8;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import cn.ac.ios.dmmpp.gen.IInstrumentation;
import rev.common.Kinds;
import soot.ArrayType;
import soot.BooleanType;
import soot.Local;
import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Value;
import soot.VoidType;
import soot.jimple.IntConstant;
import soot.jimple.InvokeExpr;
import soot.jimple.Jimple;
import soot.jimple.JimpleBody;
import soot.jimple.NopStmt;
import soot.jimple.NullConstant;
import soot.jimple.Stmt;
import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointConstants;

/**
 * Dummy-main generator in DMMPP's style (a static method DMMPP(formals..., boolean[])
 * in the component class; every branch reads a symbolic boolean from the array),
 * with the two dimensions of the revision as switches:
 *
 *   lifecycle  DMMPP_FIXED  DMMPP's lifecycle graphs, with two repairs: nop
 *                           placeholders for lifecycle methods the app does not
 *                           override and for join nodes (DMMPP's own generator
 *                           throws there), and the fragment graph's onResume self
 *                           loop replaced by the edge the code intended
 *              HSM          the host activity's dummy main runs the fragment
 *                           lifecycle at the synchronisation points observed on
 *                           the device; one symbolic boolean per fragment decides
 *                           whether it is attached, all its phases obey that boolean
 *
 *   params     PERARG       one formal parameter per argument occurrence (DMMPP)
 *              PERTYPE      one formal per declared type (the submitted paper)
 *              RULES        only the merges with runtime evidence: host activity,
 *                           the saved-state Bundle of a component, the view of
 *                           onCreateView/onViewCreated; everything else PERARG
 */
public final class Gen8 {

    public enum Lifecycle { DMMPP_FIXED, HSM }
    public enum Params { PERARG, PERTYPE, RULES }

    public static final class Result {
        public SootMethod dmm;
        public int formals;
        public int eventCalls;
        public final List<String> mergeLog = new ArrayList<String>();
    }

    private static final String METHOD = "DMMPP";
    private static final String F_ONATTACH_CTX = "void onAttach(android.content.Context)";
    private static final String F_ONVIEWSTATERESTORED = "void onViewStateRestored(android.os.Bundle)";

    private final SootClass comp;
    private final Lifecycle lifecycle;
    private final Params params;
    private final Result res = new Result();

    private final List<Stmt> units = new ArrayList<Stmt>();
    private final List<Local> locals = new ArrayList<Local>();
    private final List<Local> formals = new ArrayList<Local>();
    private final Map<String, Local> formalByType = new HashMap<String, Local>();
    private Local preds;
    private int predIndex = 0;
    private int localCounter = 0;
    private Local thisLocal;
    private Local stateBundle;          // RULES: the component's saved-state Bundle
    private final Map<SootClass, Local> fragBundle = new HashMap<SootClass, Local>();
    private final Map<SootClass, Local> fragInst = new HashMap<SootClass, Local>();
    private final Map<SootClass, Local> fragAttached = new HashMap<SootClass, Local>();
    private Local lastView;             // RULES: the View returned by the last onCreateView

    private Gen8(SootClass comp, Lifecycle lifecycle, Params params) {
        this.comp = comp;
        this.lifecycle = lifecycle;
        this.params = params;
    }

    // ------------------------------------------------------------------ API

    public static Result activity(SootClass act, FragmentHosts.Info hosts, Lifecycle lc, Params pm) {
        Gen8 g = new Gen8(act, lc, pm);
        g.begin();
        g.activityBody(hosts, lc == Lifecycle.HSM ? hosts.fragments : new HashSet<SootClass>(), hosts.onCreateOnly);
        return g.finish();
    }

    public static Result fragment(SootClass frag, Params pm) {
        Gen8 g = new Gen8(frag, Lifecycle.DMMPP_FIXED, pm);
        g.begin();
        g.fragmentStandaloneBody();
        return g.finish();
    }

    public static Result service(SootClass c, Params pm) {
        Gen8 g = new Gen8(c, Lifecycle.DMMPP_FIXED, pm);
        g.begin();
        g.serviceBody();
        return g.finish();
    }

    public static Result receiver(SootClass c, Params pm) {
        Gen8 g = new Gen8(c, Lifecycle.DMMPP_FIXED, pm);
        g.begin();
        g.construct();
        g.call(comp(g), "void onReceive(android.content.Context,android.content.Intent)");
        g.ret();
        return g.finish();
    }

    public static Result provider(SootClass c, Params pm) {
        Gen8 g = new Gen8(c, Lifecycle.DMMPP_FIXED, pm);
        g.begin();
        g.construct();
        g.call(comp(g), "boolean onCreate()");
        NopStmt loop = g.nop();
        for (String s : new String[] { "android.database.Cursor query(android.net.Uri,java.lang.String[],java.lang.String,java.lang.String[],java.lang.String)",
                "android.net.Uri insert(android.net.Uri,android.content.ContentValues)",
                "int update(android.net.Uri,android.content.ContentValues,java.lang.String,java.lang.String[])",
                "int delete(android.net.Uri,java.lang.String,java.lang.String[])",
                "java.lang.String getType(android.net.Uri)" })
            g.call(comp(g), s);
        g.branchTo(loop);
        g.ret();
        return g.finish();
    }

    private static Local comp(Gen8 g) { return g.thisLocal; }

    // ------------------------------------------------------------------ emission helpers

    private void begin() {
        SootMethod old = comp.getMethodByNameUnsafe(METHOD);
        if (old != null)
            comp.removeMethod(old);
        preds = newLocal(ArrayType.v(BooleanType.v(), 1), "preds");
        thisLocal = newLocal(comp.getType(), "self");
    }

    private Local newLocal(Type t, String name) {
        Local l = Jimple.v().newLocal(name + "_" + (localCounter++), t);
        locals.add(l);
        return l;
    }

    private Local formal(Type t, String why) {
        Local l = newLocal(t, "p");
        formals.add(l);
        res.mergeLog.add(comp.getName() + "," + why + "," + t + ",formal#" + (formals.size() - 1));
        return l;
    }

    private NopStmt nop() {
        NopStmt n = Jimple.v().newNopStmt();
        units.add(n);
        return n;
    }

    /** symbolic branch: if preds[k] == 0 goto target */
    private void branchTo(Stmt target) {
        Local z = newLocal(BooleanType.v(), "z");
        units.add(Jimple.v().newAssignStmt(z, Jimple.v().newArrayRef(preds, IntConstant.v(predIndex++))));
        units.add(Jimple.v().newIfStmt(Jimple.v().newEqExpr(z, IntConstant.v(0)), target));
    }

    /** a symbolic boolean read once, reusable in several guards */
    private Local symbolicBoolean(String name) {
        Local z = newLocal(BooleanType.v(), name);
        units.add(Jimple.v().newAssignStmt(z, Jimple.v().newArrayRef(preds, IntConstant.v(predIndex++))));
        return z;
    }

    private void ifFalseGoto(Local z, Stmt target) {
        units.add(Jimple.v().newIfStmt(Jimple.v().newEqExpr(z, IntConstant.v(0)), target));
    }

    private void ret() {
        units.add(Jimple.v().newReturnStmt(thisLocal));
    }

    private void construct() {
        units.add(Jimple.v().newAssignStmt(thisLocal, Jimple.v().newNewExpr(comp.getType())));
        SootMethod ctor = constructorOf(comp);
        if (ctor != null)
            invoke(ctor, thisLocal, "ctor");
    }

    private static SootMethod constructorOf(SootClass c) {
        for (SootMethod m : c.getMethods())
            if (m.isConstructor())
                return m;
        return null;
    }

    /** resolves and calls a lifecycle method on the receiver if the app overrides it; returns the call or a nop */
    private Stmt call(Local recv, String subsig) {
        SootClass rc = ((RefType) recv.getType()).getSootClass();
        SootMethod m = IInstrumentation.findMethod(rc, subsig);
        if (m == null || AndroidEntryPointConstants.isLifecycleClass(m.getDeclaringClass().getName())
                || m.getDeclaringClass().getName().startsWith("android.") || m.getDeclaringClass().getName().startsWith("androidx.")
                || m.isAbstract() || !m.isConcrete())
            return nop();
        return invoke(m, recv, subsig);
    }

    private Stmt invoke(SootMethod m, Local recv, String why) {
        List<Value> args = new ArrayList<Value>();
        for (int i = 0; i < m.getParameterCount(); i++)
            args.add(argument(m, i, recv));
        InvokeExpr ie;
        if (m.isStatic())
            ie = Jimple.v().newStaticInvokeExpr(m.makeRef(), args);
        else if (m.isConstructor())
            ie = Jimple.v().newSpecialInvokeExpr(recv, m.makeRef(), args);
        else if (m.getDeclaringClass().isInterface())
            ie = Jimple.v().newInterfaceInvokeExpr(recv, m.makeRef(), args);
        else
            ie = Jimple.v().newVirtualInvokeExpr(recv, m.makeRef(), args);
        Stmt s;
        if (m.getReturnType() instanceof VoidType) {
            s = Jimple.v().newInvokeStmt(ie);
        } else {
            Local r = newLocal(m.getReturnType(), "r");
            s = Jimple.v().newAssignStmt(r, ie);
            if (m.getName().equals("onCreateView") && m.getReturnType().toString().equals("android.view.View"))
                lastView = r;
        }
        units.add(s);
        res.eventCalls++;
        return s;
    }

    /** the value for argument i of a call to m on receiver recv, according to the parameter policy */
    private Value argument(SootMethod m, int i, Local recv) {
        Type t = m.getParameterType(i);
        String key = t.toString();
        String name = m.getName();
        SootClass rc = m.getDeclaringClass();
        boolean fragment = Kinds.isFragment(rc);
        boolean activity = Kinds.isActivity(rc);
        if (params == Params.RULES) {
            // R-host: the Activity/Context a fragment is attached to is its host
            if (fragment && name.equals("onAttach") && (key.equals("android.app.Activity") || key.equals("android.content.Context"))
                    && hostForFragment != null) {
                res.mergeLog.add(comp.getName() + "," + m.getSignature() + "#" + i + "," + t + ",R-host");
                return hostForFragment;
            }
            // R-state: one saved-state Bundle per component. For an activity this includes
            // onSaveInstanceState (in-process re-creation hands the same object to the next
            // onCreate, 72/72 observations); for a fragment it does not (FragmentManager
            // reuses its scratch Bundle only when it stayed empty, 2 of 6 observations)
            boolean fragState = fragment && (name.equals("onCreate") || name.equals("onActivityCreated")
                    || name.equals("onViewCreated") || name.equals("onViewStateRestored") || name.equals("onCreateView"));
            boolean actState = activity && (name.equals("onCreate") || name.equals("onRestoreInstanceState")
                    || name.equals("onPostCreate") || name.equals("onSaveInstanceState"));
            if (key.equals("android.os.Bundle") && (fragState || actState)) {
                Local b;
                if (fragment && recv != thisLocal) {
                    SootClass fc = ((RefType) recv.getType()).getSootClass();
                    b = fragBundle.get(fc);
                    if (b == null) { b = formal(t, "R-state:" + fc.getName()); fragBundle.put(fc, b); }
                } else {
                    if (stateBundle == null) stateBundle = formal(t, "R-state:" + comp.getName());
                    b = stateBundle;
                }
                res.mergeLog.add(comp.getName() + "," + m.getSignature() + "#" + i + "," + t + ",R-state");
                return b;
            }
            // R-view: onViewCreated receives the view onCreateView returned
            if (fragment && name.equals("onViewCreated") && i == 0 && lastView != null) {
                res.mergeLog.add(comp.getName() + "," + m.getSignature() + "#" + i + "," + t + ",R-view");
                return lastView;
            }
            return formal(t, m.getSignature() + "#" + i);
        }
        if (params == Params.PERTYPE) {
            Local l = formalByType.get(key);
            if (l == null) { l = formal(t, "type:" + key); formalByType.put(key, l); }
            else res.mergeLog.add(comp.getName() + "," + m.getSignature() + "#" + i + "," + t + ",type-merge");
            return l;
        }
        return formal(t, m.getSignature() + "#" + i);
    }

    private Local hostForFragment = null;

    private Result finish() {
        List<Type> ptypes = new ArrayList<Type>();
        for (Local f : formals) ptypes.add(f.getType());
        ptypes.add(ArrayType.v(BooleanType.v(), 1));
        SootMethod m = Scene.v().makeSootMethod(METHOD, ptypes, comp.getType(), Modifier.PUBLIC | Modifier.STATIC);
        comp.addMethod(m);
        JimpleBody b = Jimple.v().newBody(m);
        m.setActiveBody(b);
        b.getLocals().addAll(locals);
        for (int i = 0; i < formals.size(); i++)
            b.getUnits().add(Jimple.v().newIdentityStmt(formals.get(i), Jimple.v().newParameterRef(formals.get(i).getType(), i)));
        b.getUnits().add(Jimple.v().newIdentityStmt(preds, Jimple.v().newParameterRef(ptypes.get(ptypes.size() - 1), formals.size())));
        b.getUnits().addAll(units);
        res.dmm = m;
        res.formals = formals.size();
        return res;
    }

    // ------------------------------------------------------------------ callbacks (as DMMPP: new listener, constructor, callback)

    private void callbackBlock(List<String> callbackSigs) {
        if (callbackSigs == null || callbackSigs.isEmpty())
            return;
        NopStmt start = nop();
        for (String sig : callbackSigs) {
            SootMethod cb;
            try { cb = Scene.v().getMethod(sig); } catch (RuntimeException e) { continue; }
            SootClass lc = cb.getDeclaringClass();
            SootMethod ctor = constructorOf(lc);
            if (ctor == null || !cb.isConcrete() || lc.isAbstract())
                continue;
            Local l = newLocal(lc.getType(), "cb");
            units.add(Jimple.v().newAssignStmt(l, Jimple.v().newNewExpr(lc.getType())));
            invoke(ctor, l, "ctor");
            invoke(cb, l, "callback");
        }
        branchTo(start);
    }

    // ------------------------------------------------------------------ activity

    private void activityBody(FragmentHosts.Info hosts, Set<SootClass> spliced, Set<SootClass> onCreateOnly) {
        NopStmt end = Jimple.v().newNopStmt();
        NopStmt top = nop();
        branchTo(end);
        construct();
        hostForFragment = thisLocal;
        for (SootClass f : spliced) {
            Local inst = newLocal(f.getType(), "frag");
            units.add(Jimple.v().newAssignStmt(inst, NullConstant.v()));
            fragInst.put(f, inst);
            fragAttached.put(f, symbolicBoolean("attached"));
        }

        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONCREATE);
        phases(spliced, "create", "view");
        NopStmt onStart = nop();
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONSTART);
        phases(spliced, "start");
        NopStmt afterRestore = Jimple.v().newNopStmt();
        branchTo(afterRestore);
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONRESTOREINSTANCESTATE);
        units.add(afterRestore);
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONPOSTCREATE);
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONRESUME);
        phases(spliced, "resume");
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONPOSTRESUME);

        // running: activity callbacks, fragment callbacks, dynamic transactions
        NopStmt loopEnd = Jimple.v().newNopStmt();
        NopStmt loopStart = nop();
        branchTo(loopEnd);
        callbackBlock(hosts.callbacks);
        for (SootClass f : spliced)
            fragmentCallbacks(f);
        for (SootClass f : spliced) {
            if (onCreateOnly.contains(f))
                continue;
            phases(java.util.Collections.singleton(f), "create", "view", "start", "resume");
            phases(java.util.Collections.singleton(f), "pause", "stop", "destroyview", "destroy");
        }
        branchTo(loopStart);
        units.add(loopEnd);

        phases(spliced, "pause");
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONPAUSE);
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONCREATEDESCRIPTION);
        NopStmt afterSave = Jimple.v().newNopStmt();
        branchTo(afterSave);
        phases(spliced, "save");
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONSAVEINSTANCESTATE);
        units.add(afterSave);
        phases(spliced, "stop");
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONSTOP);
        NopStmt toDestroy = Jimple.v().newNopStmt();
        branchTo(toDestroy);
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONRESTART);
        units.add(Jimple.v().newGotoStmt(onStart));
        units.add(toDestroy);
        phases(spliced, "destroyview", "destroy");
        call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONDESTROY);
        branchTo(top);
        units.add(end);
        ret();
    }

    /** the phases of every spliced fragment, each guarded by the fragment's attached boolean */
    private void phases(Set<SootClass> frags, String... names) {
        for (SootClass f : frags) {
            NopStmt skip = Jimple.v().newNopStmt();
            ifFalseGoto(fragAttached.get(f), skip);
            Local inst = fragInst.get(f);
            for (String p : names)
                phase(f, inst, p);
            units.add(skip);
        }
    }

    private void phase(SootClass f, Local inst, String p) {
        if (p.equals("create")) {
            units.add(Jimple.v().newAssignStmt(inst, Jimple.v().newNewExpr(f.getType())));
            SootMethod ctor = constructorOf(f);
            if (ctor != null) invoke(ctor, inst, "ctor");
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONATTACH);
            call(inst, F_ONATTACH_CTX);
            call(thisLocal, AndroidEntryPointConstants.ACTIVITY_ONATTACHFRAGMENT);
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONCREATE);
        } else if (p.equals("view")) {
            lastView = null;
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONCREATEVIEW);
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONVIEWCREATED);
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONACTIVITYCREATED);
            call(inst, F_ONVIEWSTATERESTORED);
        } else if (p.equals("start")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONSTART);
        } else if (p.equals("resume")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONRESUME);
        } else if (p.equals("pause")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONPAUSE);
        } else if (p.equals("save")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONSAVEINSTANCESTATE);
        } else if (p.equals("stop")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONSTOP);
        } else if (p.equals("destroyview")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONDESTROYVIEW);
        } else if (p.equals("destroy")) {
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONDESTROY);
            call(inst, AndroidEntryPointConstants.FRAGMENT_ONDETACH);
        }
    }

    private void fragmentCallbacks(SootClass f) {
        List<String> cbs = fragmentCallbackSigs(f);
        if (cbs.isEmpty())
            return;
        NopStmt skip = Jimple.v().newNopStmt();
        ifFalseGoto(fragAttached.get(f), skip);
        callbackBlock(cbs);
        units.add(skip);
    }

    private static List<String> fragmentCallbackSigs(SootClass f) {
        List<String> l = new ArrayList<String>();
        try {
            Set<SootClass> inv = cn.ac.ios.dmmpp.AndroidCallBacks.getSootClassesInvoked(f, null, null).mInvokedSootClasses;
            soot.util.MultiMap<SootClass, SootMethod> cb = cn.ac.ios.dmmpp.AndroidCallBacks.getCallBackMultiMap(inv);
            for (SootClass lc : cb.keySet()) for (SootMethod m : cb.get(lc)) l.add(m.getSignature());
        } catch (Throwable ignore) {}
        return l;
    }

    // ------------------------------------------------------------------ standalone fragment (DMMPP graph, repaired)

    private void fragmentStandaloneBody() {
        NopStmt end = Jimple.v().newNopStmt();
        NopStmt top = nop();
        branchTo(end);
        construct();
        NopStmt onAttach = nop();
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONATTACH);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONCREATE);
        NopStmt onCreateView = nop();
        lastView = null;
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONCREATEVIEW);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONVIEWCREATED);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONACTIVITYCREATED);
        NopStmt onStart = nop();
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONSTART);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONRESUME);
        callbackBlock(fragmentCallbackSigs(comp));
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONPAUSE);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONSAVEINSTANCESTATE);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONSTOP);
        // onStop -> onCreateView | nopAfterOnStop -> onStart | onDestroyView   (DMMPP graph)
        NopStmt afterStop = Jimple.v().newNopStmt();
        branchTo(afterStop);
        units.add(Jimple.v().newGotoStmt(onCreateView));
        units.add(afterStop);
        NopStmt toDestroyView = Jimple.v().newNopStmt();
        branchTo(toDestroyView);
        units.add(Jimple.v().newGotoStmt(onStart));
        units.add(toDestroyView);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONDESTROYVIEW);
        NopStmt toDestroy = Jimple.v().newNopStmt();
        branchTo(toDestroy);
        units.add(Jimple.v().newGotoStmt(onCreateView));
        units.add(toDestroy);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONDESTROY);
        call(thisLocal, AndroidEntryPointConstants.FRAGMENT_ONDETACH);
        branchTo(onAttach);
        branchTo(top);
        units.add(end);
        ret();
    }

    // ------------------------------------------------------------------ service (DMMPP graph)

    private void serviceBody() {
        NopStmt end = Jimple.v().newNopStmt();
        branchTo(end);
        construct();
        call(thisLocal, "void onCreate()");
        NopStmt loop = nop();
        NopStmt afterStart = Jimple.v().newNopStmt();
        branchTo(afterStart);
        call(thisLocal, "int onStartCommand(android.content.Intent,int,int)");
        units.add(afterStart);
        NopStmt afterBind = Jimple.v().newNopStmt();
        branchTo(afterBind);
        call(thisLocal, "android.os.IBinder onBind(android.content.Intent)");
        call(thisLocal, "boolean onUnbind(android.content.Intent)");
        call(thisLocal, "void onRebind(android.content.Intent)");
        units.add(afterBind);
        branchTo(loop);
        call(thisLocal, "void onDestroy()");
        units.add(end);
        ret();
    }
}

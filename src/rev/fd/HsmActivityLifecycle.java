package rev.fd;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import soot.Body;
import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Value;
import soot.jimple.Jimple;
import soot.jimple.NopStmt;
import soot.jimple.NullConstant;
import soot.jimple.Stmt;

/**
 * Emits, into a host activity's dummy main, the calls to the fragment phase
 * methods at the synchronisation points of the hierarchical lifecycle model.
 * Used by the shadowed ActivityEntryPointCreator in mode pdmm.lifecycle=hsm.
 *
 * Per hosted fragment F the host keeps a local fF (the instance) and, with
 * pdmm.alias, a Bundle sF that models F's saved state. Each phase call is
 * guarded by an opaque predicate unless pdmm.phases=mandatory.
 */
public final class HsmActivityLifecycle {

    /** the caller supplies these operations of the entry-point creator */
    public interface Host {
        Body body();
        Local intentLocal();
        Local thisLocal();
        Local newLocal(RefType t);
        void opaqueIf(Stmt target);
    }

    private final Host host;
    private final Map<SootClass, Map<FragmentPhaseCreator.Phase, SootMethod>> phases;
    private final Map<SootClass, Local> instance = new LinkedHashMap<SootClass, Local>();
    private final Map<SootClass, Local> state = new LinkedHashMap<SootClass, Local>();

    public HsmActivityLifecycle(Host host, Map<SootClass, Map<FragmentPhaseCreator.Phase, SootMethod>> phases) {
        this.host = host;
        this.phases = phases;
    }

    public boolean hasFragments() {
        return !phases.isEmpty();
    }

    /** resets the fragment instances; call at the start of every activity instance */
    public void resetInstances() {
        Jimple j = Jimple.v();
        for (SootClass f : phases.keySet())
            host.body().getUnits().add(j.newAssignStmt(instance.get(f), NullConstant.v()));
    }

    /** declares the per-fragment locals; call once, outside the activity re-creation loop,
     *  so that a fragment's saved-state Bundle survives the re-creation like the activity's */
    public void declareLocals() {
        Jimple j = Jimple.v();
        RefType bundle = RefType.v("android.os.Bundle");
        for (SootClass f : phases.keySet()) {
            Local fl = host.newLocal(f.getType());
            host.body().getUnits().add(j.newAssignStmt(fl, NullConstant.v()));
            instance.put(f, fl);
            Local sl = host.newLocal(bundle);
            if (PdmmConfig.alias()) {
                host.body().getUnits().add(j.newAssignStmt(sl, j.newNewExpr(bundle)));
                SootMethod init = bundle.getSootClass().getMethodUnsafe("void <init>()");
                if (init != null)
                    host.body().getUnits().add(j.newInvokeStmt(j.newSpecialInvokeExpr(sl, init.makeRef())));
            } else {
                host.body().getUnits().add(j.newAssignStmt(sl, NullConstant.v()));
            }
            state.put(f, sl);
        }
    }

    /** one phase for every hosted fragment, each optionally skipped */
    public void all(FragmentPhaseCreator.Phase phase) {
        for (SootClass f : phases.keySet())
            one(f, phase);
    }

    /** several phases in a row for every fragment, skipped or taken as a group */
    public void allGroup(FragmentPhaseCreator.Phase... group) {
        for (SootClass f : phases.keySet())
            group(f, group);
    }

    public void one(SootClass f, FragmentPhaseCreator.Phase phase) {
        group(f, phase);
    }

    private void group(SootClass f, FragmentPhaseCreator.Phase... group) {
        Jimple j = Jimple.v();
        NopStmt skip = j.newNopStmt();
        if (!PdmmConfig.mandatoryPhases())
            host.opaqueIf(skip);
        for (FragmentPhaseCreator.Phase p : group) {
            SootMethod m = phases.get(f).get(p);
            if (m == null)
                continue;
            if (p == FragmentPhaseCreator.Phase.SAVE && PdmmConfig.alias()) {
                // the fragment's onSaveInstanceState gets a fresh Bundle that may become the
                // saved state of its next instance (FragmentManager.java:2670-2680)
                RefType bundle = RefType.v("android.os.Bundle");
                host.body().getUnits().add(j.newAssignStmt(state.get(f), j.newNewExpr(bundle)));
                SootMethod init = bundle.getSootClass().getMethodUnsafe("void <init>()");
                if (init != null)
                    host.body().getUnits().add(j.newInvokeStmt(j.newSpecialInvokeExpr(state.get(f), init.makeRef())));
            }
            List<Value> args = new ArrayList<Value>();
            args.add(host.intentLocal());
            args.add(host.thisLocal());
            args.add(instance.get(f));
            args.add(state.get(f));
            if (p == FragmentPhaseCreator.Phase.CREATE)
                host.body().getUnits().add(j.newAssignStmt(instance.get(f), j.newStaticInvokeExpr(m.makeRef(), args)));
            else
                host.body().getUnits().add(j.newInvokeStmt(j.newStaticInvokeExpr(m.makeRef(), args)));
        }
        host.body().getUnits().add(skip);
    }

    /** the fragment instance is dropped after DESTROY */
    public void clearInstances() {
        Jimple j = Jimple.v();
        for (SootClass f : phases.keySet())
            host.body().getUnits().add(j.newAssignStmt(instance.get(f), NullConstant.v()));
    }

    /** dynamic transactions during the running phase: bring-up and tear-down of any fragment */
    public void dynamicTransactions() {
        for (SootClass f : phases.keySet()) {
            if (PdmmRegistry.onCreateOnlyFragments.contains(f) && !PdmmRegistry.dynamicFragments.contains(f))
                continue;
            group(f, FragmentPhaseCreator.Phase.CREATE, FragmentPhaseCreator.Phase.VIEW,
                    FragmentPhaseCreator.Phase.START, FragmentPhaseCreator.Phase.RESUME);
            group(f, FragmentPhaseCreator.Phase.PAUSE, FragmentPhaseCreator.Phase.STOP,
                    FragmentPhaseCreator.Phase.DESTROYVIEW, FragmentPhaseCreator.Phase.DESTROY);
        }
    }

    public static Map<FragmentPhaseCreator.Phase, SootMethod> lookupPhases(SootClass fragment) {
        Map<FragmentPhaseCreator.Phase, SootMethod> m = new LinkedHashMap<FragmentPhaseCreator.Phase, SootMethod>();
        SootClass dummy = Scene.v().getSootClassUnsafe("dummyMainClass", false);
        if (dummy == null)
            return m;
        for (FragmentPhaseCreator.Phase p : FragmentPhaseCreator.Phase.values()) {
            SootMethod sm = dummy.getMethodByNameUnsafe(FragmentPhaseCreator.methodName(p, fragment));
            if (sm != null)
                m.put(p, sm);
        }
        return m;
    }
}

package rev.fd;

import java.util.Collections;

import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootField;
import soot.SootMethod;
import soot.Type;
import soot.jimple.Jimple;
import soot.jimple.JimpleBody;
import soot.jimple.infoflow.entryPointCreators.SimulatedCodeElementTag;

/**
 * Host linkage for fragments (pdmm.alias=1): the fragment gets a synthetic field
 * pdmm_host that the CREATE phase sets to the host activity, and implementations
 * of getActivity(), getContext(), requireActivity() and requireContext() that
 * return it. This mirrors what FlowDroid already does for getIntent(): without
 * it, every read of the host through getActivity() yields an unknown object.
 */
public final class HostLinker {

    public static final String FIELD = "pdmm_host";

    private HostLinker() {}

    public static SootField link(SootClass fragment) {
        SootField f = fragment.getFieldByNameUnsafe(FIELD);
        if (f != null)
            return f;
        RefType activity = RefType.v("android.app.Activity");
        f = Scene.v().makeSootField(FIELD, activity, Modifier.PUBLIC);
        f.addTag(SimulatedCodeElementTag.TAG);
        fragment.addField(f);

        boolean androidx = isSub(fragment, "androidx.fragment.app.Fragment");
        boolean support = isSub(fragment, "android.support.v4.app.Fragment");
        String activityRet = androidx ? "androidx.fragment.app.FragmentActivity"
                : support ? "android.support.v4.app.FragmentActivity" : "android.app.Activity";
        getter(fragment, f, "getActivity", activityRet);
        getter(fragment, f, "getContext", "android.content.Context");
        if (androidx || support) {
            getter(fragment, f, "requireActivity", activityRet);
            getter(fragment, f, "requireContext", "android.content.Context");
        }
        return f;
    }

    private static void getter(SootClass fragment, SootField f, String name, String retClass) {
        SootClass rc = Scene.v().getSootClassUnsafe(retClass);
        if (rc == null)
            return;
        Type ret = rc.getType();
        String subsig = retClass + " " + name + "()";
        if (declaresInAppHierarchy(fragment, subsig))
            return;
        SootMethod m = Scene.v().makeSootMethod(name, Collections.<Type>emptyList(), ret, Modifier.PUBLIC);
        m.addTag(SimulatedCodeElementTag.TAG);
        fragment.addMethod(m);
        JimpleBody b = Jimple.v().newBody(m);
        m.setActiveBody(b);
        b.insertIdentityStmts();
        Jimple j = Jimple.v();
        soot.Local host = j.newLocal("host", f.getType());
        b.getLocals().add(host);
        b.getUnits().add(j.newAssignStmt(host, j.newInstanceFieldRef(b.getThisLocal(), f.makeRef())));
        if (ret.equals(f.getType())) {
            b.getUnits().add(j.newReturnStmt(host));
        } else {
            soot.Local cast = j.newLocal("cast", ret);
            b.getLocals().add(cast);
            b.getUnits().add(j.newAssignStmt(cast, j.newCastExpr(host, ret)));
            b.getUnits().add(j.newReturnStmt(cast));
        }
    }

    /** true if the fragment or one of its application superclasses already defines the method */
    private static boolean declaresInAppHierarchy(SootClass c, String subsig) {
        for (SootClass k = c; k != null && k.isApplicationClass(); k = k.hasSuperclass() ? k.getSuperclass() : null)
            if (k.declaresMethod(subsig))
                return true;
        return false;
    }

    private static boolean isSub(SootClass c, String base) {
        for (SootClass k = c; k != null; k = k.hasSuperclass() ? k.getSuperclass() : null)
            if (k.getName().equals(base))
                return true;
        return false;
    }
}

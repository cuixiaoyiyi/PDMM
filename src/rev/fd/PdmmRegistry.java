package rev.fd;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootField;
import soot.SootMethod;
import soot.jimple.infoflow.entryPointCreators.SimulatedCodeElementTag;

/**
 * State shared between the transaction-site instrumentation (which runs on the
 * app code before entry-point creation) and the generated dummy mains.
 *
 * The holder class PdmmHolder carries one static field per fragment class; the
 * app code stores the fragment object it hands to a FragmentTransaction into
 * that field, and the fragment's CREATE phase reads it back.
 */
public final class PdmmRegistry {

    public static final String HOLDER = "PdmmHolder";

    private PdmmRegistry() {}

    /** callbacks per fragment class, recorded by the shadowed FragmentEntryPointCreator */
    public static final Map<SootClass, Set<SootMethod>> fragmentCallbacks = new HashMap<SootClass, Set<SootMethod>>();

    /** fragment classes with a synchronous transaction site (commitNow, executePendingTransactions, DialogFragment.show) */
    public static final Set<SootClass> syncFragments = new LinkedHashSet<SootClass>();

    /** fragment classes whose transaction sites all lie in a host's onCreate (or in the layout) */
    public static final Set<SootClass> onCreateOnlyFragments = new LinkedHashSet<SootClass>();

    /** fragment classes with at least one transaction site outside onCreate */
    public static final Set<SootClass> dynamicFragments = new LinkedHashSet<SootClass>();

    /** stubs inserted at synchronous transaction sites, filled once the phase methods exist */
    public static final Map<SootClass, SootMethod> syncStubCreated = new LinkedHashMap<SootClass, SootMethod>();
    public static final Map<SootClass, SootMethod> syncStubResumed = new LinkedHashMap<SootClass, SootMethod>();

    public static void reset() {
        fragmentCallbacks.clear();
        syncFragments.clear();
        onCreateOnlyFragments.clear();
        dynamicFragments.clear();
        syncStubCreated.clear();
        syncStubResumed.clear();
    }

    public static SootClass holder() {
        SootClass sc = Scene.v().getSootClassUnsafe(HOLDER, false);
        if (sc == null) {
            sc = Scene.v().makeSootClass(HOLDER);
            sc.setResolvingLevel(SootClass.BODIES);
            sc.setSuperclass(Scene.v().getSootClass("java.lang.Object"));
            sc.addTag(SimulatedCodeElementTag.TAG);
            Scene.v().addClass(sc);
            sc.setApplicationClass();
        }
        return sc;
    }

    public static String mangle(SootClass c) {
        return c.getName().replace("_", "__").replace(".", "_").replace("$", "_S_");
    }

    /** the static field of PdmmHolder that carries the app's instance of the fragment class */
    public static SootField fragmentField(SootClass fragment) {
        SootClass h = holder();
        String name = "frag_" + mangle(fragment);
        SootField f = h.getFieldByNameUnsafe(name);
        if (f == null) {
            f = Scene.v().makeSootField(name, RefType.v(fragment), Modifier.PUBLIC | Modifier.STATIC);
            h.addField(f);
        }
        return f;
    }
}

package cn.ac.ios.pdmm;

import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Canonical Android lifecycle specification used to judge the validity of an
 * edge (u -> v) in a generated dummy-main control-flow graph.
 *
 * Two layers:
 *  (1) Intra-component FSM validity: the ordered transition relation delta of
 *      the standard Activity / Fragment lifecycle (Android official docs).
 *  (2) Hierarchical rho mapping: which Fragment macro-states are legal while
 *      the host Activity is in a given macro-state (Table I of the paper).
 *
 * Methods are identified by their Soot sub-signature strings (as produced by
 * FlowDroid's AndroidEntryPointConstants), so the spec is independent of how
 * any particular generator names things.
 */
public final class LifecycleSpec {

    public enum Comp { ACTIVITY, FRAGMENT, OTHER }

    /* ---- macro-state ordinals (monotone with lifecycle progress) ---- */
    // Activity
    public static final int A_INIT = 0, A_CREATED = 1, A_STARTED = 2, A_RESUMED = 3,
            A_PAUSED = 4, A_STOPPED = 5, A_DESTROYED = 6;
    // Fragment
    public static final int F_INIT = 0, F_ATTACHED = 1, F_CREATED = 2, F_VIEWCREATED = 3,
            F_ACTCREATED = 4, F_STARTED = 5, F_RESUMED = 6, F_PAUSED = 7, F_STOPPED = 8,
            F_VIEWDESTROYED = 9, F_DESTROYED = 10, F_DETACHED = 11;

    /* sub-signature -> macro state, for Activity and Fragment respectively */
    private static final Map<String, Integer> ACT_STATE = new HashMap<>();
    private static final Map<String, Integer> FRAG_STATE = new HashMap<>();

    /* canonical valid directed edges, keyed "u==>v" on sub-signatures */
    private static final Set<String> VALID_ACT = new HashSet<>();
    private static final Set<String> VALID_FRAG = new HashSet<>();

    /* rho: Activity macro-state -> set of permissible Fragment macro-states */
    private static final Map<Integer, Set<Integer>> RHO = new LinkedHashMap<>();

    /* sub-signatures (mirror AndroidEntryPointConstants, verified via Probe) */
    public static final String A_onCreate = "void onCreate(android.os.Bundle)";
    public static final String A_onStart = "void onStart()";
    public static final String A_onRestoreInstanceState = "void onRestoreInstanceState(android.os.Bundle)";
    public static final String A_onPostCreate = "void onPostCreate(android.os.Bundle)";
    public static final String A_onResume = "void onResume()";
    public static final String A_onPostResume = "void onPostResume()";
    public static final String A_onPause = "void onPause()";
    public static final String A_onCreateDescription = "java.lang.CharSequence onCreateDescription()";
    public static final String A_onSaveInstanceState = "void onSaveInstanceState(android.os.Bundle)";
    public static final String A_onStop = "void onStop()";
    public static final String A_onRestart = "void onRestart()";
    public static final String A_onDestroy = "void onDestroy()";

    public static final String F_onAttach = "void onAttach(android.app.Activity)";
    public static final String F_onCreate = "void onCreate(android.os.Bundle)";
    public static final String F_onCreateView =
            "android.view.View onCreateView(android.view.LayoutInflater,android.view.ViewGroup,android.os.Bundle)";
    public static final String F_onViewCreated = "void onViewCreated(android.view.View,android.os.Bundle)";
    public static final String F_onActivityCreated = "void onActivityCreated(android.os.Bundle)";
    public static final String F_onStart = "void onStart()";
    public static final String F_onResume = "void onResume()";
    public static final String F_onPause = "void onPause()";
    public static final String F_onSaveInstanceState = "void onSaveInstanceState(android.os.Bundle)";
    public static final String F_onStop = "void onStop()";
    public static final String F_onDestroyView = "void onDestroyView()";
    public static final String F_onDestroy = "void onDestroy()";
    public static final String F_onDetach = "void onDetach()";

    static {
        /* ---- Activity state map ---- */
        ACT_STATE.put(A_onCreate, A_CREATED);
        ACT_STATE.put(A_onRestoreInstanceState, A_CREATED);
        ACT_STATE.put(A_onPostCreate, A_CREATED);
        ACT_STATE.put(A_onStart, A_STARTED);
        ACT_STATE.put(A_onRestart, A_STARTED);
        ACT_STATE.put(A_onResume, A_RESUMED);
        ACT_STATE.put(A_onPostResume, A_RESUMED);
        ACT_STATE.put(A_onPause, A_PAUSED);
        ACT_STATE.put(A_onCreateDescription, A_PAUSED);
        ACT_STATE.put(A_onSaveInstanceState, A_PAUSED);
        ACT_STATE.put(A_onStop, A_STOPPED);
        ACT_STATE.put(A_onDestroy, A_DESTROYED);

        /* ---- Fragment state map ---- */
        FRAG_STATE.put(F_onAttach, F_ATTACHED);
        FRAG_STATE.put(F_onCreate, F_CREATED);
        FRAG_STATE.put(F_onCreateView, F_VIEWCREATED);
        FRAG_STATE.put(F_onViewCreated, F_VIEWCREATED);
        FRAG_STATE.put(F_onActivityCreated, F_ACTCREATED);
        FRAG_STATE.put(F_onStart, F_STARTED);
        FRAG_STATE.put(F_onResume, F_RESUMED);
        FRAG_STATE.put(F_onPause, F_PAUSED);
        FRAG_STATE.put(F_onSaveInstanceState, F_PAUSED);
        FRAG_STATE.put(F_onStop, F_STOPPED);
        FRAG_STATE.put(F_onDestroyView, F_VIEWDESTROYED);
        FRAG_STATE.put(F_onDestroy, F_DESTROYED);
        FRAG_STATE.put(F_onDetach, F_DETACHED);

        /* ---- canonical Activity edges (Android docs) ---- */
        addAct(A_onCreate, A_onStart);
        addAct(A_onStart, A_onRestoreInstanceState);
        addAct(A_onStart, A_onPostCreate);
        addAct(A_onRestoreInstanceState, A_onPostCreate);
        addAct(A_onPostCreate, A_onResume);
        addAct(A_onResume, A_onPostResume);
        addAct(A_onPostResume, A_onPause);
        addAct(A_onResume, A_onPause);
        addAct(A_onPause, A_onResume);          // back to foreground
        addAct(A_onPause, A_onCreateDescription);
        addAct(A_onPause, A_onSaveInstanceState);
        addAct(A_onPause, A_onStop);
        addAct(A_onCreateDescription, A_onSaveInstanceState);
        addAct(A_onCreateDescription, A_onStop);
        addAct(A_onSaveInstanceState, A_onStop);
        addAct(A_onStop, A_onRestart);
        addAct(A_onStop, A_onDestroy);
        addAct(A_onRestart, A_onStart);

        /* ---- canonical Fragment edges (Android docs) ---- */
        addFrag(F_onAttach, F_onCreate);
        addFrag(F_onCreate, F_onCreateView);
        addFrag(F_onCreateView, F_onViewCreated);
        addFrag(F_onViewCreated, F_onActivityCreated);
        addFrag(F_onActivityCreated, F_onStart);
        addFrag(F_onStart, F_onResume);
        addFrag(F_onResume, F_onPause);
        addFrag(F_onPause, F_onResume);          // back to foreground
        addFrag(F_onPause, F_onSaveInstanceState);
        addFrag(F_onPause, F_onStop);
        addFrag(F_onSaveInstanceState, F_onStop);
        addFrag(F_onStop, F_onStart);            // restart (re-enter started)
        addFrag(F_onStop, F_onDestroyView);
        addFrag(F_onDestroyView, F_onCreateView);// re-show from back stack
        addFrag(F_onDestroyView, F_onDestroy);
        addFrag(F_onDestroy, F_onDetach);

        /* ---- rho mapping (Table I of paper, extended monotonically) ---- */
        RHO.put(A_INIT, setOf(F_INIT, F_ATTACHED, F_CREATED));
        RHO.put(A_CREATED, setOf(F_INIT, F_ATTACHED, F_CREATED, F_VIEWCREATED, F_ACTCREATED));
        RHO.put(A_STARTED, union(RHO.get(A_CREATED), setOf(F_STARTED)));
        RHO.put(A_RESUMED, union(RHO.get(A_STARTED), setOf(F_RESUMED)));
        RHO.put(A_PAUSED, setOf(F_PAUSED, F_STOPPED, F_VIEWDESTROYED, F_DESTROYED, F_DETACHED));
        RHO.put(A_STOPPED, setOf(F_STOPPED, F_VIEWDESTROYED, F_DESTROYED, F_DETACHED));
        RHO.put(A_DESTROYED, setOf(F_VIEWDESTROYED, F_DESTROYED, F_DETACHED));
    }

    private static void addAct(String u, String v) { VALID_ACT.add(u + "==>" + v); }
    private static void addFrag(String u, String v) { VALID_FRAG.add(u + "==>" + v); }

    private static Set<Integer> setOf(Integer... xs) { return new HashSet<>(Arrays.asList(xs)); }
    private static Set<Integer> union(Set<Integer> a, Set<Integer> b) {
        Set<Integer> r = new HashSet<>(a); r.addAll(b); return r;
    }

    public static boolean isActivityMethod(String subsig) { return ACT_STATE.containsKey(subsig); }
    public static boolean isFragmentMethod(String subsig) { return FRAG_STATE.containsKey(subsig); }

    public static int activityState(String subsig) { return ACT_STATE.getOrDefault(subsig, -1); }
    public static int fragmentState(String subsig) { return FRAG_STATE.getOrDefault(subsig, -1); }

    /** Is an intra-Activity edge valid per the canonical Activity FSM? */
    public static boolean validActivityEdge(String u, String v) { return VALID_ACT.contains(u + "==>" + v); }

    /** Is an intra-Fragment edge valid per the canonical Fragment FSM? */
    public static boolean validFragmentEdge(String u, String v) { return VALID_FRAG.contains(u + "==>" + v); }

    /** rho: is Fragment macro-state f permissible while Activity is in macro-state a? */
    public static boolean rhoAllows(int activityState, int fragmentState) {
        Set<Integer> allowed = RHO.get(activityState);
        return allowed != null && allowed.contains(fragmentState);
    }

    private LifecycleSpec() {}
}

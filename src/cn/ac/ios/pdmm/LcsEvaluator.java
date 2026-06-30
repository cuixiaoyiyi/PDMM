package cn.ac.ios.pdmm;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import cn.ac.ios.dmmpp.lifecycle.LifecycleGraph;
import cn.ac.ios.dmmpp.lifecycle.Node;

/**
 * Lifecycle Consistency Score (LCS) evaluation (RQ2).
 *
 * LCS(tool) = (# generated lifecycle edges (u,v) that are valid per the
 * canonical Android lifecycle spec) / (# generated lifecycle edges).
 *
 * Edge sets per tool:
 *   - FlowDroid : any-callback-after-any-callback model (the naive
 *     non-deterministic loop). For a fragment-hosting activity FlowDroid inlines
 *     the fragment lifecycle, so its pool is the union of both method sets.
 *   - DMMPP     : the *real* structured graphs produced by
 *     LifecycleGraphActivity / LifecycleGraphFragment (extracted here), with
 *     Activities and Fragments modelled as disjoint graphs (no rho sync).
 *   - Ours(HSM) : Activity backbone + rho-bounded Fragment splice with
 *     synchronized cross edges (commit deferred / commitNow inlined).
 */
public class LcsEvaluator {

    public enum Comp { ACT, FRAG }

    public static final class Edge {
        final String u, v; final Comp cu, cv;
        Edge(String u, Comp cu, String v, Comp cv) { this.u = u; this.cu = cu; this.v = v; this.cv = cv; }
        public String toString() { return cu + ":" + u + " -> " + cv + ":" + v; }
        public boolean equals(Object o){ if(!(o instanceof Edge))return false; Edge e=(Edge)o;
            return u.equals(e.u)&&v.equals(e.v)&&cu==e.cu&&cv==e.cv; }
        public int hashCode(){ return (u+v+cu+cv).hashCode(); }
    }

    public static final class Score {
        public int valid, total;
        public double lcs() { return total == 0 ? 1.0 : (double) valid / total; }
        public void add(Score s){ valid += s.valid; total += s.total; }
    }

    /* ---------- edge classification against the canonical spec ---------- */
    public static boolean isValid(Edge e) {
        if (e.cu == Comp.ACT && e.cv == Comp.ACT) return LifecycleSpec.validActivityEdge(e.u, e.v);
        if (e.cu == Comp.FRAG && e.cv == Comp.FRAG) return LifecycleSpec.validFragmentEdge(e.u, e.v);
        if (e.cu == Comp.ACT && e.cv == Comp.FRAG) // splice into fragment: fragment state must be legal under activity state
            return LifecycleSpec.rhoAllows(LifecycleSpec.activityState(e.u), LifecycleSpec.fragmentState(e.v));
        if (e.cu == Comp.FRAG && e.cv == Comp.ACT) // returning to activity: current fragment state legal under entered activity state
            return LifecycleSpec.rhoAllows(LifecycleSpec.activityState(e.v), LifecycleSpec.fragmentState(e.u));
        return false;
    }

    public static Score score(Set<Edge> edges) {
        Score s = new Score();
        for (Edge e : edges) {
            // only count edges where both endpoints are known lifecycle methods
            boolean known = (e.cu == Comp.ACT ? LifecycleSpec.isActivityMethod(e.u) : LifecycleSpec.isFragmentMethod(e.u))
                         && (e.cv == Comp.ACT ? LifecycleSpec.isActivityMethod(e.v) : LifecycleSpec.isFragmentMethod(e.v));
            if (!known) continue;
            s.total++;
            if (isValid(e)) s.valid++;
        }
        return s;
    }

    /* ---------- DMMPP: extract real edges from a LifecycleGraph ---------- */
    public static Set<Edge> dmmppEdges(LifecycleGraph g, Comp comp) {
        Set<Edge> edges = new LinkedHashSet<>();
        for (Node n : g.getNodes()) {
            if (n.isNopNode()) continue;            // only start from a real lifecycle method
            String u = n.getMethodSubSig();
            for (Node succ : realSuccessors(n)) {
                edges.add(new Edge(u, comp, succ.getMethodSubSig(), comp));
            }
        }
        return edges;
    }

    /** follow firstSucc/secondSucc, skipping nop/callback/head/bottom nodes, to
     *  the next nodes that carry a real lifecycle sub-signature. */
    private static List<Node> realSuccessors(Node start) {
        List<Node> out = new ArrayList<>();
        Set<Node> visited = new HashSet<>();
        ArrayDeque<Node> q = new ArrayDeque<>();
        push(q, start.getFirstSucc()); push(q, start.getSecondSucc());
        while (!q.isEmpty()) {
            Node cur = q.poll();
            if (cur == null || !visited.add(cur)) continue;
            if (!cur.isNopNode()) { out.add(cur); continue; }   // reached a real method
            push(q, cur.getFirstSucc()); push(q, cur.getSecondSucc());
        }
        return out;
    }
    private static void push(ArrayDeque<Node> q, Node n) { if (n != null) q.add(n); }

    /* ---------- FlowDroid: any-to-any model over a method set ---------- */
    public static Set<Edge> flowDroidEdges(List<String> actMethods, List<String> fragMethods) {
        // union pool with component tags; any method may follow any other.
        List<String[]> pool = new ArrayList<>(); // [subsig, comp]
        for (String m : actMethods)  pool.add(new String[]{m, "ACT"});
        for (String m : fragMethods) pool.add(new String[]{m, "FRAG"});
        Set<Edge> edges = new LinkedHashSet<>();
        for (int i = 0; i < pool.size(); i++)
            for (int j = 0; j < pool.size(); j++) {
                if (i == j) continue;
                edges.add(new Edge(pool.get(i)[0], comp(pool.get(i)[1]),
                                   pool.get(j)[0], comp(pool.get(j)[1])));
            }
        return edges;
    }
    private static Comp comp(String s){ return "ACT".equals(s) ? Comp.ACT : Comp.FRAG; }

    /* ---------- Ours: rho-synchronized HSM edges ---------- */
    /**
     * Build the synchronized edge set for an Activity that hosts a Fragment.
     * @param sync  SYNCHRONOUS (commitNow) inlines fragment start right after the
     *              activity reaches Created; ASYNCHRONOUS (commit) defers it to the
     *              post-resume sync point.
     */
    public static Set<Edge> hsmEdges(boolean hostsFragment, boolean commitNow) {
        Set<Edge> edges = new LinkedHashSet<>();
        // Activity backbone (canonical, all valid)
        String[][] aback = {
            {LifecycleSpec.A_onCreate, LifecycleSpec.A_onStart},
            {LifecycleSpec.A_onStart, LifecycleSpec.A_onPostCreate},
            {LifecycleSpec.A_onPostCreate, LifecycleSpec.A_onResume},
            {LifecycleSpec.A_onResume, LifecycleSpec.A_onPostResume},
            {LifecycleSpec.A_onPostResume, LifecycleSpec.A_onPause},
            {LifecycleSpec.A_onPause, LifecycleSpec.A_onSaveInstanceState},
            {LifecycleSpec.A_onSaveInstanceState, LifecycleSpec.A_onStop},
            {LifecycleSpec.A_onStop, LifecycleSpec.A_onRestart},
            {LifecycleSpec.A_onRestart, LifecycleSpec.A_onStart},
            {LifecycleSpec.A_onStop, LifecycleSpec.A_onDestroy},
        };
        for (String[] e : aback) edges.add(new Edge(e[0], Comp.ACT, e[1], Comp.ACT));
        if (!hostsFragment) return edges;

        // Fragment bring-up (canonical, all valid)
        String[][] fup = {
            {LifecycleSpec.F_onAttach, LifecycleSpec.F_onCreate},
            {LifecycleSpec.F_onCreate, LifecycleSpec.F_onCreateView},
            {LifecycleSpec.F_onCreateView, LifecycleSpec.F_onViewCreated},
            {LifecycleSpec.F_onViewCreated, LifecycleSpec.F_onActivityCreated},
            {LifecycleSpec.F_onActivityCreated, LifecycleSpec.F_onStart},
            {LifecycleSpec.F_onStart, LifecycleSpec.F_onResume},
        };
        for (String[] e : fup) edges.add(new Edge(e[0], Comp.FRAG, e[1], Comp.FRAG));
        // Fragment tear-down synchronized with activity pause/stop
        String[][] fdown = {
            {LifecycleSpec.F_onResume, LifecycleSpec.F_onPause},
            {LifecycleSpec.F_onPause, LifecycleSpec.F_onStop},
            {LifecycleSpec.F_onStop, LifecycleSpec.F_onDestroyView},
            {LifecycleSpec.F_onDestroyView, LifecycleSpec.F_onDestroy},
            {LifecycleSpec.F_onDestroy, LifecycleSpec.F_onDetach},
        };
        for (String[] e : fdown) edges.add(new Edge(e[0], Comp.FRAG, e[1], Comp.FRAG));

        // Synchronized cross (splice) edges enforcing rho
        if (commitNow) {
            // commitNow: fragment attaches immediately, still bounded by Created
            edges.add(new Edge(LifecycleSpec.A_onCreate, Comp.ACT, LifecycleSpec.F_onAttach, Comp.FRAG));
        } else {
            // commit: deferred to the post-resume sync point; activity is Started/Resumed
            edges.add(new Edge(LifecycleSpec.A_onStart, Comp.ACT, LifecycleSpec.F_onAttach, Comp.FRAG));
        }
        // fragment resumed only after activity resumed; fragment paused before activity paused
        edges.add(new Edge(LifecycleSpec.A_onPostResume, Comp.ACT, LifecycleSpec.F_onResume, Comp.FRAG));
        edges.add(new Edge(LifecycleSpec.F_onPause, Comp.FRAG, LifecycleSpec.A_onPause, Comp.ACT));
        return edges;
    }

    public static List<String> activityMethodList() {
        List<String> l = new ArrayList<>();
        l.add(LifecycleSpec.A_onCreate); l.add(LifecycleSpec.A_onStart);
        l.add(LifecycleSpec.A_onRestoreInstanceState); l.add(LifecycleSpec.A_onPostCreate);
        l.add(LifecycleSpec.A_onResume); l.add(LifecycleSpec.A_onPostResume);
        l.add(LifecycleSpec.A_onPause); l.add(LifecycleSpec.A_onSaveInstanceState);
        l.add(LifecycleSpec.A_onStop); l.add(LifecycleSpec.A_onRestart); l.add(LifecycleSpec.A_onDestroy);
        return l;
    }
    public static List<String> fragmentMethodList() {
        List<String> l = new ArrayList<>();
        l.add(LifecycleSpec.F_onAttach); l.add(LifecycleSpec.F_onCreate);
        l.add(LifecycleSpec.F_onCreateView); l.add(LifecycleSpec.F_onViewCreated);
        l.add(LifecycleSpec.F_onActivityCreated); l.add(LifecycleSpec.F_onStart);
        l.add(LifecycleSpec.F_onResume); l.add(LifecycleSpec.F_onPause);
        l.add(LifecycleSpec.F_onStop); l.add(LifecycleSpec.F_onDestroyView);
        l.add(LifecycleSpec.F_onDestroy); l.add(LifecycleSpec.F_onDetach);
        return l;
    }
}

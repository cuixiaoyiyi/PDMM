package cn.ac.ios.pdmm;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import soot.RefType;
import soot.Scene;
import soot.Type;
import soot.FastHierarchy;

/**
 * Parameter Equivalence Partitioning (Section III-C of the paper).
 *
 * Given the multiset of formal-parameter slots that the baseline DMMPP would
 * emit for one component, compute the number of symbolic variables retained by:
 *
 *   - baseline      : no merging                          |Pi|
 *   - conservative  : merge only exact-same-type slots that sit on the
 *                     dominator backbone (Scon, 100% safe)
 *   - aggressive    : merge by type compatibility (subtype folding) within the
 *                     component's single reachable lifecycle scope (Sagg)
 *
 * The result object also carries the type breakdown so we can audit merges.
 */
public class ParamPartitioner {

    public static class Result {
        public int baseline;
        public int conservative;
        public int aggressive;
        public Map<String, Integer> baselineByType = new HashMap<>();   // type -> #slots
        public Map<String, Integer> aggregatedClasses = new HashMap<>();// representative type -> #folded types
        public double prrConservative() { return baseline == 0 ? 0 : 100.0 * (baseline - conservative) / baseline; }
        public double prrAggressive()   { return baseline == 0 ? 0 : 100.0 * (baseline - aggressive)   / baseline; }
    }

    public static Result partition(List<ParamSlot> slots) {
        Result r = new Result();
        r.baseline = slots.size();
        if (slots.isEmpty()) return r;

        /* ---- conservative: exact type, dominator-only merge ---- */
        Set<String> backboneTypesSeen = new HashSet<>();
        int conservative = 0;
        for (ParamSlot s : slots) {
            r.baselineByType.merge(s.typeKey(), 1, Integer::sum);
            if (s.isDominator()) {
                if (backboneTypesSeen.add(s.typeKey())) conservative++; // first backbone slot of this exact type
                // subsequent backbone slots of same type are merged away
            } else {
                conservative++; // each callback slot kept distinct (no dominance)
            }
        }
        r.conservative = conservative;

        /* ---- aggressive: type-compatibility folding over all slots ---- */
        // distinct declared types
        List<Type> distinct = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (ParamSlot s : slots) if (seen.add(s.typeKey())) distinct.add(s.type);

        int n = distinct.size();
        int[] uf = new int[n];
        for (int i = 0; i < n; i++) uf[i] = i;
        FastHierarchy fh = null;
        try { fh = Scene.v().getOrMakeFastHierarchy(); } catch (Throwable ignore) {}

        for (int i = 0; i < n; i++) {
            for (int j = i + 1; j < n; j++) {
                if (compatible(distinct.get(i), distinct.get(j), fh)) union(uf, i, j);
            }
        }
        Map<Integer, Integer> classSize = new HashMap<>();
        Map<Integer, String> classRep = new HashMap<>();
        for (int i = 0; i < n; i++) {
            int root = find(uf, i);
            classSize.merge(root, 1, Integer::sum);
            // pick the most general (super) type in the class as representative
            String cur = classRep.get(root);
            String cand = distinct.get(i).toString();
            if (cur == null || isMoreGeneral(distinct.get(i), cur, fh)) classRep.put(root, cand);
        }
        r.aggressive = classSize.size();
        for (Map.Entry<Integer, Integer> e : classSize.entrySet())
            r.aggregatedClasses.put(classRep.get(e.getKey()), e.getValue());
        return r;
    }

    /** Two types are mergeable aggressively iff one is a subtype of the other
     *  (strict type-compatibility constraint, Eq. 5). Identical types trivially. */
    private static boolean compatible(Type a, Type b, FastHierarchy fh) {
        if (a.equals(b)) return true;
        if (!(a instanceof RefType) || !(b instanceof RefType)) return false; // primitives/arrays: exact only
        if (fh == null) return false;
        try {
            return fh.canStoreType(a, b) || fh.canStoreType(b, a);
        } catch (Throwable t) { return false; }
    }

    private static boolean isMoreGeneral(Type cand, String currentRep, FastHierarchy fh) {
        if (fh == null || !(cand instanceof RefType)) return false;
        try {
            RefType cur = Scene.v().getRefTypeUnsafe(currentRep);
            if (cur == null) return false;
            // cand is more general if current can be stored into cand
            return fh.canStoreType(cur, cand);
        } catch (Throwable t) { return false; }
    }

    private static int find(int[] uf, int x) { while (uf[x] != x) { uf[x] = uf[uf[x]]; x = uf[x]; } return x; }
    private static void union(int[] uf, int a, int b) { uf[find(uf, a)] = find(uf, b); }
}

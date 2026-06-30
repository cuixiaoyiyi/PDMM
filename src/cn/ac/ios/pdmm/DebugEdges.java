package cn.ac.ios.pdmm;

import java.util.ArrayList;
import java.util.Set;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphActivity;
import cn.ac.ios.dmmpp.lifecycle.LifecycleGraphFragment;

/** Offline check of the DMMPP edge sets (no APK needed). */
public class DebugEdges {
    public static void main(String[] a) {
        Set<LcsEvaluator.Edge> act = LcsEvaluator.dmmppEdges(new LifecycleGraphActivity(new ArrayList<>()), LcsEvaluator.Comp.ACT);
        Set<LcsEvaluator.Edge> frag = LcsEvaluator.dmmppEdges(new LifecycleGraphFragment(), LcsEvaluator.Comp.FRAG);
        System.out.println("ACTIVITY graph edges = " + act.size());
        LcsEvaluator.Score sa = LcsEvaluator.score(act);
        System.out.println("  scored total=" + sa.total + " valid=" + sa.valid + " lcs=" + sa.lcs());
        for (LcsEvaluator.Edge e : act) System.out.println("    " + (LcsEvaluator.isValid(e)?"OK  ":"BAD ") + e);

        System.out.println("FRAGMENT graph edges = " + frag.size());
        LcsEvaluator.Score sf = LcsEvaluator.score(frag);
        System.out.println("  scored total=" + sf.total + " valid=" + sf.valid + " lcs=" + sf.lcs());
        for (LcsEvaluator.Edge e : frag) System.out.println("    " + (LcsEvaluator.isValid(e)?"OK  ":"BAD ") + e);

        Set<LcsEvaluator.Edge> both = new java.util.LinkedHashSet<>(act); both.addAll(frag);
        LcsEvaluator.Score sb = LcsEvaluator.score(both);
        System.out.println("COMBINED scored total=" + sb.total + " valid=" + sb.valid + " lcs=" + sb.lcs());
    }
}

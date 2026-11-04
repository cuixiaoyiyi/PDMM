package rev.common;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import soot.Body;
import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Unit;
import soot.Value;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.InvokeExpr;
import soot.jimple.NullConstant;
import soot.jimple.Stmt;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.UnitGraph;

/**
 * Extracts, from a generated dummy main, the relation "event v can directly
 * follow event u": there is a control-flow path from the call u to the call v
 * that passes through no other event call. Calls to nested dummy mains (e.g. the
 * Fragment dummy main invoked from an Activity dummy main) are followed with one
 * context per call site, so the result describes the code as a client analysis
 * sees it after inlining.
 *
 * Every branch is taken as feasible. This is the semantics intended by the
 * generators under study: FlowDroid uses opaque predicates, DMMPP reads each
 * branch condition from a symbolic boolean[] argument.
 *
 * The class only uses Soot API that exists both in the Soot bundled with DMMPP
 * (FlowDroid 2.10) and in Soot 4.7.1 (FlowDroid 2.15.1), and Java 8 syntax.
 */
public final class DmmEdges {

    public static final String START = "START";
    public static final String END = "END";

    /** One call in a dummy main that stands for a framework-triggered event. */
    public static final class Event {
        public final String kind;      // ACT FRAG SRV RCV PRV APP CB
        public final String cls;       // class that declares the invoked method reference
        public final String name;      // method name
        public final String subsig;
        public final boolean lifecycle;

        Event(String kind, String cls, String name, String subsig, boolean lifecycle) {
            this.kind = kind; this.cls = cls; this.name = name; this.subsig = subsig; this.lifecycle = lifecycle;
        }
        /** class-independent label, e.g. ACT.onCreate */
        public String label() { return kind + "." + name; }
        public String full() { return kind + "|" + cls + "|" + subsig; }
        @Override public String toString() { return full(); }
    }

    /** An argument passed to an event call. */
    public static final class Arg {
        public final String eventFull;
        public final int index;
        public final String declaredType;
        public final String form;      // null | param<i> | local:<name> | const
        public final String ctx;
        Arg(String eventFull, int index, String declaredType, String form, String ctx) {
            this.eventFull = eventFull; this.index = index; this.declaredType = declaredType; this.form = form; this.ctx = ctx;
        }
    }

    public interface Config {
        /** true if the call targets another generated dummy main whose body is to be followed */
        boolean isSubDmm(SootMethod m);
        /** true if the call is generator plumbing and not an event */
        boolean isIgnored(SootMethod m);
    }

    public static final class Result {
        /**
         * edges between events: "from -> to -> viaNew"; from/to are Event.full(), START or END.
         * viaNew is 1 if the path allocates a new component instance between the two
         * calls (the generator restarts the component), else 0.
         */
        public final Set<String> edges = new LinkedHashSet<String>();
        public final Map<String, Event> events = new LinkedHashMap<String, Event>();
        public final List<Arg> args = new ArrayList<Arg>();
        public int eventCallSites = 0;
        public int subDmmCalls = 0;
    }

    private static final class Node {
        final Ctx ctx; final Unit unit;
        Node(Ctx ctx, Unit unit) { this.ctx = ctx; this.unit = unit; }
        @Override public boolean equals(Object o) {
            if (!(o instanceof Node)) return false;
            Node n = (Node) o; return n.ctx == ctx && n.unit == unit;
        }
        @Override public int hashCode() { return System.identityHashCode(ctx) * 31 + System.identityHashCode(unit); }
    }

    /** search state: a node plus whether a component allocation was crossed */
    private static final class State {
        final Node node; final boolean viaNew;
        State(Node node, boolean viaNew) { this.node = node; this.viaNew = viaNew; }
        @Override public boolean equals(Object o) {
            if (!(o instanceof State)) return false;
            State t = (State) o; return t.viaNew == viaNew && t.node.equals(node);
        }
        @Override public int hashCode() { return node.hashCode() * 2 + (viaNew ? 1 : 0); }
    }

    /** call-string context; instances are interned so identity comparison is valid */
    private static final class Ctx {
        final Ctx parent; final Unit callSite; final SootMethod method; final String id;
        final Map<Unit, Ctx> children = new HashMap<Unit, Ctx>();
        Ctx(Ctx parent, Unit callSite, SootMethod method, String id) {
            this.parent = parent; this.callSite = callSite; this.method = method; this.id = id;
        }
        boolean onStack(SootMethod m) {
            for (Ctx c = this; c != null; c = c.parent) if (c.method.equals(m)) return true;
            return false;
        }
    }

    private final Config cfg;
    private final Map<SootMethod, UnitGraph> graphs = new HashMap<SootMethod, UnitGraph>();
    private final Result res = new Result();
    private int ctxCounter = 0;

    private DmmEdges(Config cfg) { this.cfg = cfg; }

    public static Result extract(SootMethod root, Config cfg) {
        DmmEdges x = new DmmEdges(cfg);
        x.run(root);
        return x.res;
    }

    private UnitGraph graph(SootMethod m) {
        UnitGraph g = graphs.get(m);
        if (g == null) {
            g = new BriefUnitGraph(m.getActiveBody());
            graphs.put(m, g);
        }
        return g;
    }

    private void run(SootMethod root) {
        Ctx rootCtx = new Ctx(null, null, root, "c0");
        Set<Node> seenEvents = new HashSet<Node>();
        ArrayDeque<Node> work = new ArrayDeque<Node>();

        List<Node> starts = new ArrayList<Node>();
        for (Unit h : graph(root).getHeads()) starts.add(new Node(rootCtx, h));
        for (Node v : nextEvents(starts, START)) if (seenEvents.add(v)) work.add(v);

        while (!work.isEmpty()) {
            Node u = work.poll();
            Event eu = eventOf(u);
            recordArgs(u, eu);
            List<Node> succ = successors(u);
            for (Node v : nextEvents(succ, eu.full())) if (seenEvents.add(v)) work.add(v);
        }
        res.eventCallSites = seenEvents.size();
    }

    /** successors of a node, leaving the current dummy main through return statements */
    private List<Node> successors(Node n) {
        List<Node> out = new ArrayList<Node>();
        List<Unit> succs = graph(n.ctx.method).getSuccsOf(n.unit);
        if (succs.isEmpty()) {
            if (n.ctx.parent != null)
                for (Unit s : graph(n.ctx.parent.method).getSuccsOf(n.ctx.callSite))
                    out.add(new Node(n.ctx.parent, s));
            // a return in the root context has no successor; nextEvents records END
        } else {
            for (Unit s : succs) out.add(new Node(n.ctx, s));
        }
        return out;
    }

    private void edge(String from, String to, boolean viaNew) {
        res.edges.add(from + " -> " + to + " -> " + (viaNew ? "1" : "0"));
    }

    /** forward search from the given nodes up to the first event on each path */
    private List<Node> nextEvents(List<Node> from, String fromLabel) {
        List<Node> found = new ArrayList<Node>();
        Set<State> visited = new HashSet<State>();
        ArrayDeque<State> q = new ArrayDeque<State>();
        for (Node f : from) q.add(new State(f, false));
        if (from.isEmpty()) edge(fromLabel, END, false);
        while (!q.isEmpty()) {
            State st = q.poll();
            if (!visited.add(st)) continue;
            Node n = st.node;
            boolean viaNew = st.viaNew;
            Stmt s = (Stmt) n.unit;
            if (s.containsInvokeExpr()) {
                SootMethod target = targetOf(s.getInvokeExpr());
                if (target != null && target.isConstructor()
                        && !"CB".equals(Kinds.kindOf(target.getDeclaringClass())))
                    viaNew = true;
                if (target != null && cfg.isSubDmm(target)) {
                    if (target.hasActiveBody() && !n.ctx.onStack(target)) {
                        Ctx c = n.ctx.children.get(n.unit);
                        if (c == null) {
                            c = new Ctx(n.ctx, n.unit, target, "c" + (++ctxCounter));
                            n.ctx.children.put(n.unit, c);
                            res.subDmmCalls++;
                        }
                        for (Unit h : graph(target).getHeads()) q.add(new State(new Node(c, h), viaNew));
                        continue;
                    }
                    // body missing or recursive: the call is transparent
                } else if (target != null && isEvent(target)) {
                    Event e = eventOf(n);
                    res.events.put(e.full(), e);
                    edge(fromLabel, e.full(), viaNew);
                    found.add(n);
                    continue;
                }
            }
            List<Node> succ = successors(n);
            if (succ.isEmpty() && n.ctx.parent == null && graph(n.ctx.method).getSuccsOf(n.unit).isEmpty())
                edge(fromLabel, END, viaNew);
            for (Node x : succ) q.add(new State(x, viaNew));
        }
        return found;
    }

    private static SootMethod targetOf(InvokeExpr ie) {
        try { return ie.getMethod(); } catch (RuntimeException e) { return null; }
    }

    private boolean isEvent(SootMethod m) {
        if (m.isConstructor() || m.isStaticInitializer()) return false;
        return !cfg.isIgnored(m);
    }

    private Event eventOf(Node n) {
        InvokeExpr ie = ((Stmt) n.unit).getInvokeExpr();
        SootMethod m = ie.getMethod();
        SootClass recv = m.getDeclaringClass();
        if (ie instanceof InstanceInvokeExpr) {
            Type t = ((InstanceInvokeExpr) ie).getBase().getType();
            if (t instanceof RefType) recv = ((RefType) t).getSootClass();
        }
        String kind = Kinds.kindOf(recv);
        boolean lc = Kinds.isLifecycle(kind, m.getName());
        return new Event(kind, recv.getName(), m.getName(), m.getSubSignature(), lc);
    }

    private void recordArgs(Node n, Event e) {
        InvokeExpr ie = ((Stmt) n.unit).getInvokeExpr();
        Body body = n.ctx.method.getActiveBody();
        List<Local> params;
        try { params = body.getParameterLocals(); } catch (RuntimeException ex) { params = Collections.<Local>emptyList(); }
        for (int i = 0; i < ie.getArgCount(); i++) {
            Value v = ie.getArg(i);
            String form;
            if (v instanceof NullConstant) form = "null";
            else if (v instanceof Local) {
                int pi = params.indexOf(v);
                form = pi >= 0 ? "param" + pi : "local:" + ((Local) v).getName();
            } else form = "const";
            res.args.add(new Arg(e.full(), i, ie.getMethod().getParameterType(i).toString(), form, n.ctx.id));
        }
    }
}

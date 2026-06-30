package cn.ac.ios.dmmpp.gen;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;

import cn.ac.ios.dmmpp.lifecycle.LifecycleGraph;
import cn.ac.ios.dmmpp.lifecycle.Node;
import soot.Local;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Value;
import soot.jimple.AssignStmt;
import soot.jimple.Jimple;
import soot.jimple.Stmt;

/**
 * Parameter-de-bloated DMM generator (the real artifact for RQ1).
 *
 * Identical control-flow structure to DMMPP's {@link DMMGen}, but instead of
 * synthesizing one formal parameter per consumed callback argument, it allocates
 * exactly one symbolic formal parameter per *distinct declared type* within the
 * component scope (Parameter Equivalence Partitioning, exact-type variant — the
 * safe subset that always yields JVM-verifiable Jimple). Every callback argument
 * of type T is then supplied from the single shared local for T, which both
 * shrinks the signature and explicitly encodes the alias relationship that the
 * baseline destroys.
 *
 * The aggressive subtype-folding variant is used only for *counting* (RQ1
 * metrics); for emitted code we keep exact-type merging so no super->sub
 * assignment can break verification.
 */
public class PDMMGen extends AbstractDMMGen {

    private final Map<Node, List<Stmt>> map = new HashMap<>();

    /** distinct declared type (toString) -> index of its shared formal parameter */
    private final Map<String, Integer> typeToParam = new LinkedHashMap<>();

    /** when false, behave like the baseline DMMPP: one formal parameter per
     *  consumed argument (no merging). Used as the de-bloating control. */
    private final boolean mergeParams;
    private int consumeIdx = 0;   // sequential cursor for the no-merge path

    /** bookkeeping for the report */
    public int baselineParamCount = 0;   // what DMMGen would have emitted
    public int reducedParamCount = 0;    // what we emit

    public PDMMGen(SootClass component, LifecycleGraph graph) { this(component, graph, true); }

    public PDMMGen(SootClass component, LifecycleGraph graph, boolean mergeParams) {
        this.component = component;
        this.graph = graph;
        this.mergeParams = mergeParams;

        // Walk the graph exactly as DMMGen does, registering parameter slots.
        for (Node node : graph.getNodes()) {
            if (!node.isNopNode()) {
                SootMethod m = IInstrumentation.findMethod(component, node.getMethodSubSig());
                if (m != null) for (Type t : m.getParameterTypes()) register(t);
            } else if (node.isCallbackNode()) {
                for (String sig : node.getCallbacks()) {
                    SootMethod cb;
                    try { cb = Scene.v().getMethod(sig); } catch (Throwable t) { continue; }
                    SootMethod ctor = getConstructor(cb.getDeclaringClass());
                    if (ctor != null) {
                        for (Type t : ctor.getParameterTypes()) register(t);
                        for (Type t : cb.getParameterTypes()) register(t);
                    }
                }
            }
        }

        if (mergeParams) {
            reducedParamCount = typeToParam.size();
            for (Map.Entry<String, Integer> e : sortedByIndex())
                mArgList.add(typeByName.get(e.getKey()));
        } else {
            reducedParamCount = allTypesInOrder.size();   // == baseline (one per slot)
            mArgList.addAll(allTypesInOrder);
        }
    }

    private final Map<String, Type> typeByName = new HashMap<>();
    private final List<Type> allTypesInOrder = new ArrayList<>();  // every slot, in order
    private void register(Type t) {
        baselineParamCount++;
        allTypesInOrder.add(t);
        String k = t.toString();
        if (!typeToParam.containsKey(k)) {
            typeToParam.put(k, typeToParam.size());
            typeByName.put(k, t);
        }
    }
    private List<Map.Entry<String, Integer>> sortedByIndex() {
        List<Map.Entry<String, Integer>> l = new ArrayList<>(typeToParam.entrySet());
        l.sort((a, b) -> Integer.compare(a.getValue(), b.getValue()));
        return l;
    }

    /** Supply each argument: merged -> shared per-type parameter; baseline ->
     *  a fresh sequential parameter (matching registration order). */
    @Override
    public List<Value> getArgumentsFromParameters(SootMethod methodToCall) {
        List<Value> args = new LinkedList<>();
        for (int i = 0; i < methodToCall.getParameterCount(); i++) {
            int idx;
            if (mergeParams) {
                Integer t = typeToParam.get(methodToCall.getParameterType(i).toString());
                idx = (t == null) ? 0 : t;
            } else {
                idx = Math.min(consumeIdx++, mArgList.size() - 2); // -1 is boolean[]
            }
            args.add(getParameterLocal(idx));
        }
        return args;
    }

    /* ---- control-flow synthesis: identical to DMMGen ---- */

    @Override
    public void addNonExplicitlyInheritedLifecycleMethod() {
        for (Node node : graph.getNodes())
            if (!node.isNopNode())
                addLifeCycleMethod(node.getMethodSubSig(), component, component.getSuperclass());
    }

    @Override
    public void generateComponentLifecycle() {
        generateInvokeStmtForEachNode();
        generateGotoStmt();
    }

    private void generateGotoStmt() {
        for (Node node : graph.getNodes()) {
            if (!node.isReturnNode() && !node.isHead()) {
                int index1 = findBlock(map.get(node));
                List<Stmt> succ = stmts.get(index1 + 1);
                boolean isNext = succ.equals(map.get(node.getFirstSucc()));
                if (!isNext && node.isBranchNode())
                    isNext = succ.equals(map.get(node.getSecondSucc()));
                if (!isNext)
                    map.get(node).add(Jimple.v().newGotoStmt(map.get(node.getFirstSucc()).get(0)));
            }
        }
        for (Node node : graph.getNodes()) {
            if (node.isBranchNode()) {
                Node succ = node.getFirstSucc();
                int index1 = findBlock(map.get(node));
                int index2 = findBlock(map.get(succ));
                if (index2 == (index1 + 1)) succ = node.getSecondSucc();
                List<Stmt> ifstmts = createIfStmt(map.get(succ).get(0));
                map.get(node).addAll(ifstmts);
            }
        }
    }

    private int findBlock(List<Stmt> list) {
        for (int i = 0; i < stmts.size(); i++) if (list.equals(stmts.get(i))) return i;
        return -1;
    }

    private void generateInvokeStmtForEachNode() {
        for (Node node : graph.getNodes()) {
            List<Stmt> list = new ArrayList<>();
            if (!node.isNopNode()) {
                Stmt stmt = searchAndBuildMethod(node.getMethodSubSig(), component, thisLocal);
                // A lifecycle method not overridden by the app resolves to null
                // (its body lives in the framework). DMMPP leaves a null here and
                // then NPEs when the block is used as a branch target; we emit an
                // addressable nop placeholder so the CFG stays well-formed.
                if (stmt == null) stmt = Jimple.v().newNopStmt();
                list.add(stmt);
                map.put(node, list);
                stmts.add(list);
            } else if (node.isReturnNode()) {
                list.add(Jimple.v().newReturnStmt(thisLocal));
                map.put(node, list);
                stmts.add(list);
            } else if (node.isCallbackNode()) {
                for (String callback : node.getCallbacks()) {
                    SootMethod sootMethod = Scene.v().getMethod(callback);
                    SootMethod constructor = getConstructor(sootMethod.getDeclaringClass());
                    if (constructor != null) {
                        Local caller = mLocalGenerator.generateLocal(sootMethod.getDeclaringClass().getType());
                        AssignStmt newAssign = Jimple.v().newAssignStmt(caller,
                                Jimple.v().newNewExpr(sootMethod.getDeclaringClass().getType()));
                        Stmt initStmt = searchAndBuildMethod(constructor.getSubSignature(), sootMethod.getDeclaringClass(), caller);
                        Stmt callbackInvocation = searchAndBuildMethod(sootMethod.getSubSignature(), sootMethod.getDeclaringClass(), caller);
                        if (initStmt != null && callbackInvocation != null) {
                            list.add(newAssign); list.add(initStmt); list.add(callbackInvocation);
                        }
                    }
                }
                map.put(node, list);
                stmts.add(list);
            } else if (node.isHead()) {
                SootMethod constructor = getConstructor(component);
                if (constructor != null) {
                    list.add(Jimple.v().newAssignStmt(thisLocal, Jimple.v().newNewExpr(component.getType())));
                    list.add(searchAndBuildMethod(constructor.getSubSignature(), component, thisLocal));
                }
                map.put(node, list);
                stmts.add(list);
            } else {
                // Intermediate nop join node (e.g. nopAfterOnStop in the Fragment
                // graph). DMMPP leaves these unmapped, which makes its own DMMGen
                // crash with an NPE on fragment-bearing apps; we emit an
                // addressable nop so control flow can target/fall through it.
                list.add(Jimple.v().newNopStmt());
                map.put(node, list);
                stmts.add(list);
            }
        }
    }

    private void addLifeCycleMethod(String methodName, SootClass myClass, SootClass libClass) {
        SootMethod sootMethod = IInstrumentation.findMethod(myClass, methodName);
        if (sootMethod != null && sootMethod.getDeclaringClass().equals(myClass)) return;
        SootMethod superMethod = null;
        try { superMethod = libClass.getMethodUnsafe(methodName); } catch (Exception ignore) {}
        if (superMethod == null) return;
        if (sootMethod == null || sootMethod.getSignature().equals(superMethod.getSignature())) {
            sootMethod = Scene.v().makeSootMethod(superMethod.getName(), superMethod.getParameterTypes(),
                    superMethod.getReturnType(), superMethod.getModifiers());
            myClass.addMethod(sootMethod);
            soot.jimple.JimpleBody body = Jimple.v().newBody(sootMethod);
            body.insertIdentityStmts();
            sootMethod.setActiveBody(body);
            soot.LocalGenerator lg = new soot.javaToJimple.DefaultLocalGenerator(body);
            final soot.jimple.InvokeExpr ie = Jimple.v().newSpecialInvokeExpr(body.getThisLocal(),
                    superMethod.makeRef(), body.getParameterLocals());
            if (superMethod.getReturnType() instanceof soot.VoidType) {
                body.getUnits().add(Jimple.v().newInvokeStmt(ie));
                body.getUnits().add(Jimple.v().newReturnVoidStmt());
            } else {
                Local ret = lg.generateLocal(superMethod.getReturnType());
                body.getUnits().add(Jimple.v().newAssignStmt(ret, ie));
                body.getUnits().add(Jimple.v().newReturnStmt(ret));
            }
        }
    }
}

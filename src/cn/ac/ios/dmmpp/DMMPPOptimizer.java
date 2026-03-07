package cn.ac.ios.dmmpp;
import soot.*;
import soot.jimple.*;
import java.util.*;

/**
 * DMMPP Optimizer: Implements highly formalized precise dummy main method generation.
 */
public class DMMPPOptimizer {

    
    public enum ActivityState {
        INITIALIZED, CREATED, STARTED, RESUMED, PAUSED, STOPPED, DESTROYED
    }

    public enum FragmentState {
        INITIALIZED, ATTACHED, CREATED, VIEW_CREATED, ACTIVITY_CREATED,
        STARTED, RESUMED, PAUSED, STOPPED, VIEW_DESTROYED, DESTROYED, DETACHED
    }

    public Set<FragmentState> getPermissibleFragmentStates(ActivityState aState) {
        Set<FragmentState> allowed = new HashSet<>();
        allowed.add(FragmentState.INITIALIZED); // Base state is always allowed before progression
        
        switch (aState) {
            case CREATED:
                allowed.addAll(Arrays.asList(
                    FragmentState.ATTACHED, FragmentState.CREATED, 
                    FragmentState.VIEW_CREATED, FragmentState.ACTIVITY_CREATED
                ));
                break;
            case STARTED:
                allowed.addAll(getPermissibleFragmentStates(ActivityState.CREATED));
                allowed.add(FragmentState.STARTED);
                break;
            case RESUMED:
                allowed.addAll(getPermissibleFragmentStates(ActivityState.STARTED));
                allowed.add(FragmentState.RESUMED);
                break;
            case PAUSED:
            case STOPPED:
            case DESTROYED:
                // Tear-down states
                allowed.addAll(Arrays.asList(
                    FragmentState.PAUSED, FragmentState.STOPPED, 
                    FragmentState.VIEW_DESTROYED, FragmentState.DESTROYED, FragmentState.DETACHED
                ));
                break;
            default:
                break;
        }
        return allowed;
    }

    static class Parameter {
        Type type;
        SootMethod hostMethod;
        int originalIndex;
        // Constructor & getters omitted for brevity
    }

    public List<Set<Parameter>> partitionParameters(List<Parameter> universePi) {
        List<Set<Parameter>> equivalenceClasses = new ArrayList<>();

        for (Parameter p : universePi) {
            boolean merged = false;
            for (Set<Parameter> eqClass : equivalenceClasses) {
                Parameter rep = eqClass.iterator().next();
                
                boolean typeCompatible = isTypeCompatible(p.type, rep.type);
                
                boolean scopeIntersects = checkScopeIntersection(p.hostMethod, rep.hostMethod);
                
                boolean aliasPlausible = checkAliasPlausibility(p.hostMethod, rep.hostMethod);

                if (typeCompatible && scopeIntersects && aliasPlausible) {
                    eqClass.add(p);
                    merged = true;
                    break;
                }
            }
            if (!merged) {
                Set<Parameter> newClass = new HashSet<>();
                newClass.add(p);
                equivalenceClasses.add(newClass);
            }
        }
        return equivalenceClasses;
    }

    private boolean isTypeCompatible(Type t1, Type t2) {
        FastHierarchy hierarchy = Scene.v().getOrMakeFastHierarchy();
        return hierarchy.canStoreType(t1, t2) || hierarchy.canStoreType(t2, t1);
    }

    private boolean checkScopeIntersection(SootMethod m1, SootMethod m2) {
        int stage1 = getLifecycleStage(m1.getName());
        int stage2 = getLifecycleStage(m2.getName());

        if (stage1 == -1 || stage2 == -1) {
            return true;
        }

        int diff = Math.abs(stage1 - stage2);
        return diff <= 2; 
    }

    private int getLifecycleStage(String methodName) {
        switch (methodName) {
            case "onAttach": return 0;
            case "onCreate": return 1;
            case "onViewCreated":
            case "onActivityCreated": return 2;
            case "onStart": return 3;
            case "onResume": return 4;
            case "onPause": return 5;
            case "onStop": return 6;
            case "onDestroyView": return 7;
            case "onDestroy": return 8;
            case "onDetach": return 9;
            default: return -1; // 交互事件或非标准生命周期方法
        }
    }

    private boolean checkAliasPlausibility(SootMethod m1, SootMethod m2) {
        if (hasKillingDefInMethod(m1) || hasKillingDefInMethod(m2)) {
            return false; // 存在潜在的 Killing Def，不允许合并
        }
        return true;
    }

    private boolean hasKillingDefInMethod(SootMethod method) {
        if (!method.hasActiveBody()) return false;
        
        for (Unit unit : method.getActiveBody().getUnits()) {
            if (unit instanceof AssignStmt) {
                AssignStmt assign = (AssignStmt) unit;
                Value rightOp = assign.getRightOp();
                if (rightOp instanceof NewExpr) {
                    String typeName = ((NewExpr) rightOp).getBaseType().toString();
                    if (typeName.equals("android.os.Bundle") || typeName.equals("android.content.Intent")) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private void injectCallbackInvocation(PatchingChain<Unit> units, SootMethod cb, Map<Set<Parameter>, Local> symLocals, Local baseInstance) {
        List<Value> args = new ArrayList<>();

        for (int i = 0; i < cb.getParameterCount(); i++) {
            Type paramType = cb.getParameterType(i);
            Local mappedLocal = null;
            for (Map.Entry<Set<Parameter>, Local> entry : symLocals.entrySet()) {
                Type symType = entry.getValue().getType();
                FastHierarchy hierarchy = Scene.v().getOrMakeFastHierarchy();
                if (hierarchy.canStoreType(symType, paramType) || hierarchy.canStoreType(paramType, symType)) {
                    mappedLocal = entry.getValue();
                    break;
                }
            }

            if (mappedLocal != null) {
                args.add(mappedLocal);
            } else {
                args.add(NullConstant.v());
            }
        }
        InvokeExpr invokeExpr;
        if (cb.isConstructor()) {
            invokeExpr = Jimple.v().newSpecialInvokeExpr(baseInstance, cb.makeRef(), args);
        } else {
            invokeExpr = Jimple.v().newVirtualInvokeExpr(baseInstance, cb.makeRef(), args);
        }

        InvokeStmt invokeStmt = Jimple.v().newInvokeStmt(invokeExpr);
        units.add(invokeStmt);
    }

    public SootMethod synthesizeDummyMain(SootClass mainClass, List<Set<Parameter>> vSym, Map<ActivityState, List<SootMethod>> activityCallbacks, Map<FragmentState, List<SootMethod>> fragCallbacks) {
        
        SootMethod dmm = new SootMethod("dummyMainMethod", 
                Arrays.asList(ArrayType.v(RefType.v("java.lang.String"), 1)), 
                VoidType.v(), Modifier.PUBLIC | Modifier.STATIC);
        mainClass.addMethod(dmm);
        
        JimpleBody body = Jimple.v().newBody(dmm);
        dmm.setActiveBody(body);
        PatchingChain<Unit> units = body.getUnits();

        Map<Set<Parameter>, Local> symbolicLocals = new HashMap<>();
        int symIndex = 0;
        for (Set<Parameter> eqClass : vSym) {
            Type baseType = eqClass.iterator().next().type;
            Local symLocal = Jimple.v().newLocal("sym_var_" + symIndex++, baseType);
            body.getLocals().add(symLocal);
            symbolicLocals.put(eqClass, symLocal);
            
            if (baseType instanceof RefType) {
                units.add(Jimple.v().newAssignStmt(symLocal, Jimple.v().newNewExpr((RefType) baseType)));
            }
        }

        Local sA = Jimple.v().newLocal("s_A", IntType.v());
        Local sF = Jimple.v().newLocal("s_F", IntType.v());
        body.getLocals().add(sA);
        body.getLocals().add(sF);
        
        units.add(Jimple.v().newAssignStmt(sA, IntConstant.v(0))); // 0 = INITIALIZED
        units.add(Jimple.v().newAssignStmt(sF, IntConstant.v(0)));

        Stmt loopStart = Jimple.v().newNopStmt();
        units.add(loopStart);

        for (ActivityState stateA : ActivityState.values()) {
            Stmt nextStateLabel = Jimple.v().newNopStmt();
            
            units.add(Jimple.v().newIfStmt(
                Jimple.v().newNeExpr(sA, IntConstant.v(stateA.ordinal())), 
                nextStateLabel
            ));

            if (activityCallbacks.containsKey(stateA)) {
                for (SootMethod cb : activityCallbacks.get(stateA)) {
                    injectCallbackInvocation(units, cb, symbolicLocals);
                }
            }

            Set<FragmentState> validFragStates = getPermissibleFragmentStates(stateA);
            
            for (FragmentState stateF : validFragStates) {
                Stmt nextFragLabel = Jimple.v().newNopStmt();
                units.add(Jimple.v().newIfStmt(
                    Jimple.v().newNeExpr(sF, IntConstant.v(stateF.ordinal())), 
                    nextFragLabel
                ));
                
                if (fragCallbacks.containsKey(stateF)) {
                    for (SootMethod fCb : fragCallbacks.get(stateF)) {
                        injectCallbackInvocation(units, fCb, symbolicLocals);
                    }
                }
                
                units.add(Jimple.v().newAssignStmt(sF, IntConstant.v(getNextFragState(stateF).ordinal())));
                units.add(nextFragLabel);
            }

            units.add(Jimple.v().newAssignStmt(sA, IntConstant.v(getNextActivityState(stateA).ordinal())));
            
            units.add(nextStateLabel);
        }

        units.add(Jimple.v().newGotoStmt(loopStart));
        units.add(Jimple.v().newReturnVoidStmt());

        return dmm;
    }

    private ActivityState getNextActivityState(ActivityState current) {
        return (current.ordinal() < ActivityState.values().length - 1) 
            ? ActivityState.values()[current.ordinal() + 1] : ActivityState.DESTROYED;
    }
    
    private FragmentState getNextFragState(FragmentState current) {
        return (current.ordinal() < FragmentState.values().length - 1) 
            ? FragmentState.values()[current.ordinal() + 1] : FragmentState.DETACHED;
    }
}
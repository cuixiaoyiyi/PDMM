package rev.fd;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootField;
import soot.SootMethod;
import soot.Type;
import soot.jimple.AssignStmt;
import soot.jimple.Jimple;
import soot.jimple.NopStmt;
import soot.jimple.NullConstant;
import soot.jimple.Stmt;
import soot.jimple.infoflow.android.entryPointCreators.AndroidEntryPointConstants;
import soot.jimple.infoflow.android.entryPointCreators.ComponentExchangeInfo;
import soot.jimple.infoflow.android.entryPointCreators.components.FragmentEntryPointCreator;
import soot.jimple.infoflow.android.manifest.IManifestHandler;
import soot.jimple.toolkits.scalar.NopEliminator;

/**
 * Generates one phase of a fragment's lifecycle as a static method
 *
 *   F pdmm_<phase>_<F>(Intent intent, Activity host, F fragment, Bundle state)
 *
 * so that the host activity's dummy main can call the phases at the points where
 * the framework runs them. The CREATE phase constructs the fragment unless the
 * caller (or, with transaction-site instrumentation, the app) already supplies
 * an instance; every phase returns the instance it worked on.
 *
 * Phases follow the observed framework order (FragBench traces):
 *   CREATE      onAttach(Activity), onAttach(Context), host.onAttachFragment, onCreate
 *   VIEW        onCreateView, onViewCreated, onActivityCreated, onViewStateRestored
 *   START       onStart
 *   RESUME      onResume
 *   CALLBACKS   the fragment's own callbacks, in an opaque loop
 *   PAUSE       onPause
 *   SAVE        onSaveInstanceState
 *   STOP        onStop
 *   DESTROYVIEW onDestroyView
 *   DESTROY     onDestroy, onDetach
 */
public class FragmentPhaseCreator extends FragmentEntryPointCreator {

    public enum Phase { CREATE, VIEW, START, RESUME, CALLBACKS, PAUSE, SAVE, STOP, DESTROYVIEW, DESTROY }

    private static final String FRAGMENT_ONATTACH_CONTEXT = "void onAttach(android.content.Context)";
    private static final String FRAGMENT_ONVIEWSTATERESTORED = "void onViewStateRestored(android.os.Bundle)";

    private final Phase phase;
    private final SootClass hostClass;

    public FragmentPhaseCreator(SootClass fragment, SootClass hostClass, SootClass applicationClass,
            IManifestHandler manifest, SootField instantiatorField, SootField classLoaderField,
            ComponentExchangeInfo componentExchangeInfo, Phase phase) {
        super(fragment, applicationClass, manifest, instantiatorField, classLoaderField, componentExchangeInfo);
        this.phase = phase;
        this.hostClass = hostClass;
        setDummyMethodName("pdmm_" + phase.name().toLowerCase());
        setCallbacks(PdmmRegistry.fragmentCallbacks.get(fragment));
    }

    /** name of the phase method of a fragment, as created by createEmptyMainMethod */
    public static String methodName(Phase phase, SootClass fragment) {
        String componentPart = fragment.getName();
        if (componentPart.contains("."))
            componentPart = componentPart.replace("_", "__").replace(".", "_");
        return "pdmm_" + phase.name().toLowerCase() + "_" + componentPart;
    }

    @Override
    protected List<Type> getAdditionalMainMethodParams() {
        List<Type> l = new ArrayList<Type>();
        l.add(RefType.v(AndroidEntryPointConstants.ACTIVITYCLASS));
        l.add(component.getType());
        l.add(RefType.v("android.os.Bundle"));
        return l;
    }

    /** the exact fragment class, so that the phase methods are typed precisely (also for androidx fragments) */
    @Override
    protected SootClass getModelledClass() {
        return component;
    }

    @Override
    protected SootMethod createDummyMainInternal() {
        final Jimple j = Jimple.v();
        final Local activityParam = body.getParameterLocal(1);
        final Local fragParam = body.getParameterLocal(2);
        final Local bundleParam = body.getParameterLocal(3);
        final SootClass bundleClass = Scene.v().getSootClass("android.os.Bundle");
        final SootClass activityClass = Scene.v().getSootClass(AndroidEntryPointConstants.ACTIVITYCLASS);

        thisLocal = generator.generateLocal(component.getType());
        body.getUnits().add(j.newAssignStmt(thisLocal, fragParam));
        localVarsForClasses.put(component, thisLocal);

        // the host with its concrete type, so that its own lifecycle methods resolve
        Local hostLocal = generator.generateLocal(hostClass.getType());
        body.getUnits().add(j.newAssignStmt(hostLocal, j.newCastExpr(activityParam, hostClass.getType())));
        localVarsForClasses.put(hostClass, hostLocal);
        localVarsForClasses.put(activityClass, activityParam);

        Set<SootClass> parents = new HashSet<SootClass>();
        parents.add(component);
        parents.add(hostClass);
        parents.add(activityClass);
        if (PdmmConfig.alias()) {
            localVarsForClasses.put(bundleClass, bundleParam);
            parents.add(bundleClass);
        }

        switch (phase) {
        case CREATE: {
            NopStmt haveInstance = j.newNopStmt();
            body.getUnits().add(j.newIfStmt(j.newNeExpr(fragParam, NullConstant.v()), haveInstance));
            if (PdmmConfig.txsite()) {
                // the object the app handed to the FragmentTransaction, if any
                SootField f = PdmmRegistry.fragmentField(component);
                body.getUnits().add(j.newAssignStmt(thisLocal, j.newStaticFieldRef(f.makeRef())));
                body.getUnits().add(j.newIfStmt(j.newNeExpr(thisLocal, NullConstant.v()), haveInstance));
            }
            // FlowDroid's generateClassConstructor returns an already registered local of
            // the class instead of allocating, so the registrations (the parameter local
            // and thisLocal) are dropped for the allocation
            localVarsForClasses.remove(component);
            Local created = generateClassConstructor(component);
            if (created != null && created != thisLocal)
                body.getUnits().add(j.newAssignStmt(thisLocal, created));
            body.getUnits().add(haveInstance);
            localVarsForClasses.put(component, thisLocal);
            if (PdmmConfig.alias()) {
                // host linkage: getActivity()/getContext() of the fragment return this host
                SootField hf = HostLinker.link(component);
                body.getUnits().add(j.newAssignStmt(j.newInstanceFieldRef(thisLocal, hf.makeRef()), activityParam));
            }
            body.getUnits().add(j.newInvokeStmt(j.newInterfaceInvokeExpr(thisLocal,
                    componentExchangeInfo.setIntentMethod.makeRef(), java.util.Arrays.asList((soot.Value) intentLocal))));
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONATTACH, thisLocal, parents);
            searchAndBuildMethod(FRAGMENT_ONATTACH_CONTEXT, thisLocal, parents);
            searchAndBuildMethod(AndroidEntryPointConstants.ACTIVITY_ONATTACHFRAGMENT, hostLocal, parents);
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONCREATE, thisLocal, parents);
            break;
        }
        case VIEW: {
            Stmt s = searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONCREATEVIEW, thisLocal, parents);
            if (PdmmConfig.alias() && s instanceof AssignStmt && ((AssignStmt) s).getLeftOp() instanceof Local) {
                // the view returned by onCreateView is the view passed to onViewCreated
                Local view = (Local) ((AssignStmt) s).getLeftOp();
                SootClass viewClass = Scene.v().getSootClass("android.view.View");
                localVarsForClasses.put(viewClass, view);
                parents.add(viewClass);
            }
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONVIEWCREATED, thisLocal, parents);
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONACTIVITYCREATED, thisLocal, parents);
            searchAndBuildMethod(FRAGMENT_ONVIEWSTATERESTORED, thisLocal, parents);
            break;
        }
        case START:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONSTART, thisLocal, parents);
            break;
        case RESUME:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONRESUME, thisLocal, parents);
            break;
        case CALLBACKS:
            addCallbackMethods();
            break;
        case PAUSE:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONPAUSE, thisLocal, parents);
            break;
        case SAVE:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONSAVEINSTANCESTATE, thisLocal, parents);
            break;
        case STOP:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONSTOP, thisLocal, parents);
            break;
        case DESTROYVIEW:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONDESTROYVIEW, thisLocal, parents);
            break;
        case DESTROY:
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONDESTROY, thisLocal, parents);
            searchAndBuildMethod(AndroidEntryPointConstants.FRAGMENT_ONDETACH, thisLocal, parents);
            break;
        }

        // only CREATE hands the instance back; the other phases return null so that the
        // taint abstraction of the instance is not re-created at every phase call
        // (which made FlowDroid's path reconstruction explode)
        body.getUnits().add(j.newReturnStmt(phase == Phase.CREATE ? (soot.Value) thisLocal : NullConstant.v()));
        NopEliminator.v().transform(body);
        return mainMethod;
    }
}

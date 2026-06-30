package cn.ac.ios.pdmm;

import soot.Type;

/**
 * One formal-parameter slot that the baseline DMMPP generator would allocate at
 * the dummy-main entry: it records the declared Java type plus where the
 * argument is consumed (which drives the conservative/aggressive merge rules).
 */
public class ParamSlot {
    public final Type type;
    public final String hostSig;     // signature of the consuming callback/lifecycle method
    public final Kind kind;

    public enum Kind {
        /** parameter of a linear lifecycle method (onCreate/onStart/...) -> on the
         *  dominator backbone, so it is safely mergeable even conservatively. */
        BACKBONE,
        /** parameter of a UI/event callback invoked inside the non-deterministic
         *  loop -> repeated, no dominance, conservatively kept distinct. */
        CALLBACK,
        /** parameter of a constructor call (dominates everything). */
        CONSTRUCTOR
    }

    public ParamSlot(Type type, String hostSig, Kind kind) {
        this.type = type;
        this.hostSig = hostSig;
        this.kind = kind;
    }

    public String typeKey() { return type.toString(); }

    public boolean isDominator() { return kind == Kind.BACKBONE || kind == Kind.CONSTRUCTOR; }
}

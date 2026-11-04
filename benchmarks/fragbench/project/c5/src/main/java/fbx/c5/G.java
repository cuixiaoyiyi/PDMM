package fbx.c5;

import android.app.Activity;
import androidx.fragment.app.Fragment;
import android.content.Context;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;

public class G extends Fragment {
    String data;

    @Override
    public void onAttach(Activity activity) {
        super.onAttach(activity);
        T.ev("G.onAttach", "this=" + T.tag("G", this) + " a0=" + T.tag("Activity", activity));
    }

    @Override
    public void onAttach(Context context) {
        super.onAttach(context);
        T.ev("G.onAttachContext", "this=" + T.tag("G", this) + " a0=" + T.tag("Context", context));
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        T.ev("G.onCreate", "this=" + T.tag("G", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onViewCreated(View view, Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        T.ev("G.onViewCreated", "this=" + T.tag("G", this) + " a0=" + T.tag("View", view) + " a1=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onActivityCreated(Bundle savedInstanceState) {
        super.onActivityCreated(savedInstanceState);
        T.ev("G.onActivityCreated", "this=" + T.tag("G", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onViewStateRestored(Bundle savedInstanceState) {
        super.onViewStateRestored(savedInstanceState);
        T.ev("G.onViewStateRestored", "this=" + T.tag("G", this) + " a0=" + T.tag("Bundle", savedInstanceState));
    }

    @Override
    public void onStart() {
        super.onStart();
        T.ev("G.onStart", "this=" + T.tag("G", this));
    }

    @Override
    public void onResume() {
        super.onResume();
        T.ev("G.onResume", "this=" + T.tag("G", this));
    }

    @Override
    public void onPause() {
        super.onPause();
        T.ev("G.onPause", "this=" + T.tag("G", this));
    }

    @Override
    public void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        T.ev("G.onSaveInstanceState", "this=" + T.tag("G", this) + " a0=" + T.tag("Bundle", outState));
    }

    @Override
    public void onStop() {
        super.onStop();
        T.ev("G.onStop", "this=" + T.tag("G", this));
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        T.ev("G.onDestroyView", "this=" + T.tag("G", this));
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        T.ev("G.onDestroy", "this=" + T.tag("G", this));
    }

    @Override
    public void onDetach() {
        super.onDetach();
        T.ev("G.onDetach", "this=" + T.tag("G", this));
    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {
        T.ev("G.onCreateView", "this=" + T.tag("G", this) + " a0=" + T.tag("LayoutInflater", inflater) + " a1=" + T.tag("ViewGroup", container) + " a2=" + T.tag("Bundle", savedInstanceState));
        Button v = new Button(getActivity());
        v.setText("G");
        v.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View w) {
                T.ev("G.viewClick", "this=" + T.tag("G", G.this) + " a0=" + T.tag("View", w));
            }
        });
        return v;
    }
}

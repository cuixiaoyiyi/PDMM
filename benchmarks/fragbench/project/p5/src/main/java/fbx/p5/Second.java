package fbx.p5;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public class Second extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        T.ev("Second.onCreate", "this=" + T.tag("Second", this) + " a0=" + T.tag("Bundle", savedInstanceState));
        Intent result = new Intent();
        result.putExtra("k", "clean");
        setResult(RESULT_OK, result);
        finish();
    }
}

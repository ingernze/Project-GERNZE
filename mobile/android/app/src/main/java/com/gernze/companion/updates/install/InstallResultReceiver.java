package com.gernze.companion.updates.install;

import android.content.*;

/** Must be manifest registered with exported=false. Explicit PendingIntent is the capability. */
public final class InstallResultReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent){
        final PendingResult pending=goAsync();InstallEngine engine=InstallEngine.get(context);
        engine.worker.execute(()->{try{engine.result(intent);}catch(Exception ignored){/* Persisted recovery remains authoritative; never report success on error. */}finally{pending.finish();}});
    }
}

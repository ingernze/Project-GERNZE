package com.gernze.companion;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.os.SystemClock;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.squareup.seismic.ShakeDetector;

@CapacitorPlugin(name="HebaoShake")
public final class LibaoShakePlugin extends Plugin {
    private SensorManager sensors;
    private ShakeDetector detector;
    private boolean requested, foreground = true, listening;
    private long warmUntil, lastShake = -3500;

    @Override public void load() {
        sensors = (SensorManager) getContext().getSystemService(Context.SENSOR_SERVICE);
        detector = new ShakeDetector(() -> {
            long now = SystemClock.elapsedRealtime();
            if (!listening || !requested || !foreground || now < warmUntil || now - lastShake < 3500) return;
            lastShake = now;
            notifyListeners("shake", new JSObject());
        });
        detector.setSensitivity(20); // Strong sustained acceleration; tune only after phone feedback.
    }

    private boolean available() {
        return sensors != null && sensors.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) != null;
    }

    private void stop() {
        if (detector != null) detector.stop();
        listening = false;
    }

    private void reconcile() {
        if (!requested || !foreground || !available()) { stop(); return; }
        if (!listening) {
            // UI rate, no fastest sampling, wake lock or foreground service.
            warmUntil = SystemClock.elapsedRealtime() + 750;
            listening = detector.start(sensors, SensorManager.SENSOR_DELAY_UI);
        }
    }

    @PluginMethod public void setEnabled(PluginCall call) {
        boolean value = Boolean.TRUE.equals(call.getBoolean("enabled", false));
        getActivity().runOnUiThread(() -> {
            requested = value;
            try {
                reconcile();
                JSObject result = new JSObject();
                result.put("available", available()); result.put("active", listening);
                call.resolve(result);
            } catch (RuntimeException error) {
                stop(); call.reject("摇晃检测暂不可用", "sensor_unavailable");
            }
        });
    }

    @Override protected void handleOnPause() { foreground = false; stop(); }
    @Override protected void handleOnStop() { foreground = false; stop(); }
    @Override protected void handleOnResume() { foreground = true; reconcile(); }
    @Override protected void handleOnDestroy() { requested = false; foreground = false; stop(); }
}

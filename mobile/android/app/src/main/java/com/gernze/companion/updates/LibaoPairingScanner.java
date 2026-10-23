package com.gernze.companion.updates;

import android.Manifest;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.PermissionState;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import com.journeyapps.barcodescanner.ScanOptions;
import com.journeyapps.barcodescanner.ScanIntentResult;
import java.nio.charset.StandardCharsets;

@CapacitorPlugin(name="HebaoPairingScanner",permissions={@Permission(alias="camera",strings={Manifest.permission.CAMERA})})
public final class LibaoPairingScanner extends Plugin {
    private boolean scanning;
    @PluginMethod public void scan(PluginCall call){
        if(scanning){call.reject("扫码窗口已经打开","busy");return;}
        scanning=true;
        if(getPermissionState("camera")!=PermissionState.GRANTED){requestPermissionForAlias("camera",call,"cameraReady");return;}
        startScan(call);
    }
    @PermissionCallback private void cameraReady(PluginCall call){
        if(call==null){scanning=false;return;}
        if(getPermissionState("camera")!=PermissionState.GRANTED){scanning=false;call.reject("未获得相机权限，可改用配对文件","permission_required");return;}
        startScan(call);
    }
    private void startScan(PluginCall call){
        try{
            ScanOptions options=new ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setCaptureActivity(PairingCaptureActivity.class).setOrientationLocked(false)
                .setBeepEnabled(false).setBarcodeImageEnabled(false).setTimeout(180000)
                .setPrompt("扫描自己电脑上的莉宝配对二维码");
            startActivityForResult(call,options.createScanIntent(getContext()),"scanned");
        }catch(Exception e){scanning=false;call.reject("无法打开扫码窗口，可改用配对文件","unavailable");}
    }
    @ActivityCallback private void scanned(PluginCall call,ActivityResult result){
        scanning=false;if(call==null)return;
        try{
            ScanIntentResult scan=ScanIntentResult.parseActivityResult(result.getResultCode(),result.getData());
            String text=scan.getContents();
            if(text==null){call.reject("已取消扫码","cancelled");return;}
            if(text.getBytes(StandardCharsets.UTF_8).length>8192||!"QR_CODE".equals(scan.getFormatName())){call.reject("不是莉宝配对码","invalid_input");return;}
            JSObject out=new JSObject();out.put("payload",text);call.resolve(out);
        }catch(Exception e){call.reject("无法读取配对码","invalid_input");}
    }
}

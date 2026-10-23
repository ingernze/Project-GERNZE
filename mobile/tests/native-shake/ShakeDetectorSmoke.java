package com.squareup.seismic;




public class ShakeDetectorSmoke {
    private static void assertTrue(boolean value){if(!value)throw new AssertionError();}
    private static void assertFalse(boolean value){if(value)throw new AssertionError();}
    public static void main(String[] args){
        ShakeDetectorSmoke t=new ShakeDetectorSmoke();
        t.oneBumpAmongQuietSamplesDoesNotShake();
        t.sustainedStrongSamplesTriggerAtUiRate();
        t.clearingOnStopPreventsOldSamplesFromTriggeringOnResume();
        System.out.println("Three real Seismic sample-queue traces passed; no phone sensor was tested.");
    }
    public void oneBumpAmongQuietSamplesDoesNotShake() {
        ShakeDetector.SampleQueue q=new ShakeDetector.SampleQueue();
        for(int i=0;i<20;i++) { q.add(i*60000000L,i==8); assertFalse(q.isShaking()); }
    }
    public void sustainedStrongSamplesTriggerAtUiRate() {
        ShakeDetector.SampleQueue q=new ShakeDetector.SampleQueue();
        boolean heard=false;
        for(int i=0;i<10;i++) { q.add(i*60000000L,true); heard|=q.isShaking(); }
        assertTrue(heard);
    }
    public void clearingOnStopPreventsOldSamplesFromTriggeringOnResume() {
        ShakeDetector.SampleQueue q=new ShakeDetector.SampleQueue();
        for(int i=0;i<8;i++)q.add(i*60000000L,true);
        assertTrue(q.isShaking());q.clear();q.add(9000000000L,true);assertFalse(q.isShaking());
    }
}

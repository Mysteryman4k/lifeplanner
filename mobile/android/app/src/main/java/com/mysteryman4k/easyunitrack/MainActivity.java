package com.mysteryman4k.easyunitrack;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(StreamFetchPlugin.class);          // the study assistant's streamed replies (StreamFetchPlugin.java)
        super.onCreate(savedInstanceState);
    }
}

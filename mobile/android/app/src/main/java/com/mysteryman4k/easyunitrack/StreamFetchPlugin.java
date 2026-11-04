package com.mysteryman4k.easyunitrack;

import android.util.Base64;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Streams an HTTPS request's reply to the app piece by piece, for the study assistant's AI providers.
 * The app's pages can't always call a provider directly (a service may not allow requests from web pages),
 * and the phone's other ways to make requests wait for the whole reply, which would hide a reply being written.
 *
 * start({id, url, method, headers, body, readTimeout}) resolves with {status, headers} once the reply starts;
 * its body then arrives as "chunk" events ({id, data}: base64) and ends with an "end" event ({id, error?}).
 * cancel({id}) stops it. Only https:// addresses are allowed (keys never travel unencrypted).
 */
@CapacitorPlugin(name = "StreamFetch")
public class StreamFetchPlugin extends Plugin {
    private final Map<String, HttpURLConnection> open = new ConcurrentHashMap<>();

    @PluginMethod
    public void start(PluginCall call) {
        String id = call.getString("id");
        String url = call.getString("url");
        if (id == null || url == null || !url.startsWith("https://")) {
            call.reject("Only https:// addresses can be used.");
            return;
        }
        String method = call.getString("method", "GET");
        JSObject headers = call.getObject("headers", new JSObject());
        String body = call.getString("body");
        int readTimeout = call.getInt("readTimeout", 120000);

        new Thread(() -> {
            HttpURLConnection c = null;
            boolean started = false;
            try {
                c = (HttpURLConnection) new URL(url).openConnection();
                open.put(id, c);
                c.setRequestMethod(method);
                c.setConnectTimeout(10000);
                c.setReadTimeout(readTimeout);
                c.setInstanceFollowRedirects(false);
                c.setUseCaches(false);
                for (Iterator<String> it = headers.keys(); it.hasNext(); ) {
                    String name = it.next();
                    c.setRequestProperty(name, headers.getString(name));
                }
                if (body != null) {
                    c.setDoOutput(true);
                    byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                    c.setFixedLengthStreamingMode(bytes.length);
                    try (OutputStream out = c.getOutputStream()) {
                        out.write(bytes);
                    }
                }
                int status = c.getResponseCode();
                JSObject head = new JSObject();
                head.put("status", status);
                JSObject replyHeaders = new JSObject();
                for (Map.Entry<String, List<String>> h : c.getHeaderFields().entrySet()) {
                    if (h.getKey() != null && h.getValue() != null) replyHeaders.put(h.getKey().toLowerCase(), String.join(", ", h.getValue()));
                }
                head.put("headers", replyHeaders);
                call.resolve(head);
                started = true;

                InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
                if (in != null) {
                    try (InputStream stream = in) {
                        byte[] buf = new byte[8192];
                        int n;
                        while ((n = stream.read(buf)) != -1) {
                            JSObject chunk = new JSObject();
                            chunk.put("id", id);
                            chunk.put("data", Base64.encodeToString(buf, 0, n, Base64.NO_WRAP));
                            notifyListeners("chunk", chunk);
                        }
                    }
                }
                JSObject end = new JSObject();
                end.put("id", id);
                notifyListeners("end", end);
            } catch (Exception e) {
                String kind = e instanceof java.net.SocketTimeoutException ? "timeout" : "network";
                if (!started) {
                    call.reject(kind, kind);           // failed before the reply started: the request fails, like fetch()
                    open.remove(id);
                    if (c != null) c.disconnect();
                    return;
                }
                JSObject end = new JSObject();
                end.put("id", id);
                end.put("error", kind);
                notifyListeners("end", end);
            } finally {
                open.remove(id);
                if (c != null) c.disconnect();
            }
        }).start();
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        HttpURLConnection c = open.remove(call.getString("id", ""));
        if (c != null) new Thread(c::disconnect).start();
        call.resolve();
    }
}

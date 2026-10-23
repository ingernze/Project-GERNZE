package com.gernze.companion.updates.transport;

import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.TrustManagerFactory;
import org.json.JSONObject;

/** Direct private-IP socket: no DNS lookup, system HTTP proxy or redirects. */
final class PinnedHttp implements Closeable {
    interface Control {void socket(Socket socket) throws Exception;void check() throws Exception;}
    private final SSLSocket socket;
    final InputStream input;
    final Map<String,String> headers=new HashMap<>();
    final long length;
    final int status;
    PinnedHttp(JSONObject peer,String method,String path,JSONObject body,Control control) throws Exception {
        String host=TransportRules.host(peer.getString("host"));int port=(int)TransportRules.number(peer,"port",1024,65535);
        byte[] expected=Base64.decode(peer.getString("certificateDer"),Base64.NO_WRAP);
        TransportRules.require(TransportRules.sha(expected).equals(peer.getString("certificateSha256")),"tls_mismatch");
        X509Certificate cert=(X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(new java.io.ByteArrayInputStream(expected));
        TransportRules.require(Arrays.equals(expected,cert.getEncoded()),"tls_mismatch");cert.checkValidity();cert.verify(cert.getPublicKey());
        KeyStore anchors=KeyStore.getInstance(KeyStore.getDefaultType());anchors.load(null);anchors.setCertificateEntry("scanned-only",cert);
        TrustManagerFactory tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tm.init(anchors);
        SSLContext context=SSLContext.getInstance("TLS");context.init(null,tm.getTrustManagers(),null);
        Socket raw=new Socket();control.socket(raw);
        SSLSocket secured=null;
        try{
            control.check();raw.connect(new InetSocketAddress(host,port),8000);raw.setSoTimeout(15000);
            secured=(SSLSocket)context.getSocketFactory().createSocket(raw,TransportRules.TLS_NAME,port,true);control.socket(secured);
            List<String> protocols=new ArrayList<>();for(String p:secured.getSupportedProtocols())if(p.equals("TLSv1.2")||p.equals("TLSv1.3"))protocols.add(p);
            secured.setEnabledProtocols(protocols.toArray(new String[0]));
            SSLParameters params=secured.getSSLParameters();params.setEndpointIdentificationAlgorithm("HTTPS");secured.setSSLParameters(params);
            secured.startHandshake();
            X509Certificate actual=(X509Certificate)secured.getSession().getPeerCertificates()[0];actual.checkValidity();
            TransportRules.require(MessageDigest.isEqual(expected,actual.getEncoded()),"tls_mismatch");control.check();
            byte[] data=body==null?new byte[0]:body.toString().getBytes(StandardCharsets.UTF_8);
            StringBuilder request=new StringBuilder(method+" "+path+" HTTP/1.1\r\nHost: "+host+":"+port+"\r\nConnection: close\r\nAccept-Encoding: identity\r\n");
            if(peer.has("token")){
                request.append("Authorization: Bearer ").append(TransportRules.token(peer.getString("token"))).append("\r\nX-Hebao-Pairing: ").append(TransportRules.uuid(peer.getString("pairingId"))).append("\r\n");
            }
            if(body!=null)request.append("Content-Type: application/json\r\nContent-Length: ").append(data.length).append("\r\n");
            request.append("\r\n");OutputStream output=secured.getOutputStream();output.write(request.toString().getBytes(StandardCharsets.US_ASCII));output.write(data);output.flush();
            input=secured.getInputStream();String start=line(input,1024);
            TransportRules.require(start.matches("HTTP/1\\.[01] [0-9]{3}( [ -~]*)?"),"integrity_failed");status=Integer.parseInt(start.substring(9,12));
            int count=0,total=start.length();String h;
            while(!(h=line(input,4096)).isEmpty()){
                total+=h.length();TransportRules.require(++count<=32&&total<=16384,"integrity_failed");
                int colon=h.indexOf(':');TransportRules.require(colon>0,"integrity_failed");String k=h.substring(0,colon).toLowerCase(java.util.Locale.ROOT);
                TransportRules.require(k.matches("[a-z0-9-]+")&&!headers.containsKey(k),"integrity_failed");headers.put(k,h.substring(colon+1).trim());
            }
            TransportRules.require(!headers.containsKey("transfer-encoding")&&!headers.containsKey("content-range")&&
                (!headers.containsKey("content-encoding")||headers.get("content-encoding").equals("identity")),"integrity_failed");
            String len=headers.get("content-length");TransportRules.require(len!=null&&len.matches("0|[1-9][0-9]{0,9}"),"integrity_failed");length=Long.parseLong(len);
            TransportRules.require(length<=TransportRules.MAX_APK,"integrity_failed");
            socket=secured;
            if(status>=300&&status<400)throw new TransportRules.Failure("redirect_rejected");
            if(status!=200){
                String code=status==401?"authentication_failed":"integrity_failed";
                if(length<=16384){
                    try{String given=json().getString("code");if(Arrays.asList("pairing_expired","pairing_replayed","busy","authentication_failed","integrity_failed","invalid_input","range_not_supported","memory_failed","memory_unavailable").contains(given))code=given;}
                    catch(Exception ignored){}
                }
                throw new TransportRules.Failure(code);
            }
        }catch(Exception e){if(secured!=null)try{secured.close();}catch(Exception ignored){}else try{raw.close();}catch(Exception ignored){}throw e;}
    }
    private static String line(InputStream in,int max) throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();int prior=-1;
        for(int count=0;count<=max;count++){
            int c=in.read();TransportRules.require(c>=0,"integrity_failed");
            if(prior==13){TransportRules.require(c==10,"integrity_failed");return out.toString("US-ASCII");}
            if(c!=13){TransportRules.require(c>=32&&c<=126,"integrity_failed");out.write(c);}prior=c;
        }throw new TransportRules.Failure("integrity_failed");
    }
    JSONObject json() throws Exception {return json(16384);}
    JSONObject json(int maximum) throws Exception {
        TransportRules.require(length<=maximum&&"application/json".equals(headers.get("content-type")),"integrity_failed");
        ByteArrayOutputStream b=new ByteArrayOutputStream();for(long i=0;i<length;i++){int c=input.read();TransportRules.require(c>=0,"integrity_failed");b.write(c);}
        TransportRules.require(input.read()==-1,"integrity_failed");
        String text;
        try{text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(b.toByteArray())).toString();}
        catch(java.nio.charset.CharacterCodingException e){throw new TransportRules.Failure("integrity_failed");}
        return TransportRules.parse(text,maximum,maximum>16384?8192:256);
    }
    @Override public void close(){try{socket.close();}catch(Exception ignored){}}
}

/*
 * bypass.js — contoh SSL Unpinning multi-framework (Java + OkHttp + TrustManager)
 * Untuk W8 Frida CLI (Frfrida).
 * Pakai: fr <target> bypass.js
 *
 * CATATAN: ini contoh dasar. Untuk Flutter/BoringSSL, gunakan script khusus
 * (mis. reFlutter / disable-flutter-tls) dan taruh .js-nya di folder ini juga.
 */

setTimeout(function () {
    Java.perform(function () {
        console.log('[*] SSL Unpinning start...');

        // 1) Universal TrustManager (javax.net.ssl.X509TrustManager)
        try {
            var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
            var SSLContext = Java.use('javax.net.ssl.SSLContext');

            var TrustManager = Java.registerClass({
                name: 'com.w8.TrustAll',
                implements: [X509TrustManager],
                methods: {
                    checkClientTrusted: function () {},
                    checkServerTrusted: function () {},
                    getAcceptedIssuers: function () { return []; },
                },
            });

            var TrustManagers = [TrustManager.$new()];
            var initOverload = SSLContext.init.overload(
                '[Ljavax.net.ssl.KeyManager;',
                '[Ljavax.net.ssl.TrustManager;',
                'java.security.SecureRandom'
            );
            initOverload.implementation = function (km, tm, sr) {
                initOverload.call(this, km, TrustManagers, sr);
                console.log('[+] SSLContext.init() di-hook (TrustAll)');
            };
        } catch (e) {
            console.log('[-] TrustManager hook gagal: ' + e);
        }

        // 2) OkHttp3 CertificatePinner
        try {
            var CertificatePinner = Java.use('okhttp3.CertificatePinner');
            CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function () {
                console.log('[+] OkHttp3 CertificatePinner.check() dilewati');
                return;
            };
        } catch (e) {
            console.log('[-] OkHttp3 pinner tidak ada / gagal: ' + e);
        }

        // 3) TrustManagerImpl (Android 7+ / Conscrypt)
        try {
            var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
            TrustManagerImpl.verifyChain.implementation = function (untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
                console.log('[+] TrustManagerImpl.verifyChain() dilewati untuk ' + host);
                return untrustedChain;
            };
        } catch (e) {
            console.log('[-] TrustManagerImpl tidak ada / gagal: ' + e);
        }

        console.log('[*] SSL Unpinning aktif.');
    });
}, 0);

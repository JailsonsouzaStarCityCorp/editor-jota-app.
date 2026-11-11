package com.jota.editor;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.media.MediaScannerConnection;
import android.provider.MediaStore;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Editor Jota: abre o painel do editor (que roda no Termux) em tela cheia.
 * Se o painel nao estiver ligado, liga sozinho pelo Termux (RUN_COMMAND).
 */
public class MainActivity extends Activity {
    static final String PAINEL = "http://127.0.0.1:8080/";
    static final String TERMUX = "com.termux";
    static final String HOME = "/data/data/com.termux/files/home";
    static final String BIN = "/data/data/com.termux/files/usr/bin";
    static final String REPO = "https://github.com/JailsonsouzaStarCityCorp/editor-jota-app.";
    static final String INSTALAR = "curl -sL " + REPO + "/raw/main/instalar.sh | bash";
    static final int REQ_PERM = 7, REQ_ARQ = 8;

    WebView web;
    ValueCallback<Uri[]> arquivoCb;
    final Handler h = new Handler(Looper.getMainLooper());
    boolean noPainel = false;
    int tentativas = 0;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(Color.parseColor("#0d0d10"));
        getWindow().setNavigationBarColor(Color.parseColor("#0d0d10"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0d0d10"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.addJavascriptInterface(new Ponte(), "Android");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                if (url.startsWith(PAINEL) && !url.contains("/saida?") && !url.contains("/tmp?")) return false;
                if (url.startsWith("file:")) return false;
                abrirFora(url);
                return true;
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (url.startsWith(PAINEL)) {
                    // botao de configuracoes do app dentro do painel
                    v.evaluateJavascript("(function(){if(document.getElementById('appCfg'))return;var h=document.querySelector('header');" +
                            "if(!h)return;var b=document.createElement('button');b.id='appCfg';b.textContent='⚙️';" +
                            "b.style.cssText='margin-left:8px;padding:6px 10px;font-size:16px';b.onclick=function(){Android.config()};h.appendChild(b);})()", null);
                }
            }

            @Override
            public void onReceivedError(WebView v, int code, String desc, String url) {
                if (url != null && url.startsWith(PAINEL)) h.postDelayed(() -> iniciar(), 300);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (arquivoCb != null) arquivoCb.onReceiveValue(null);
                arquivoCb = cb;
                try {
                    startActivityForResult(p.createIntent(), REQ_ARQ);
                } catch (Exception e) {
                    arquivoCb = null;
                    return false;
                }
                return true;
            }
        });

        web.setDownloadListener((url, ua, cd, mime, len) -> abrirFora(url));
        iniciar();
    }

    // ------------------------------------------------------------ fluxo
    void iniciar() {
        noPainel = false;
        tentativas = 0;
        web.loadUrl("file:///android_asset/carregando.html");
        testar(true);
    }

    void testar(boolean primeira) {
        new Thread(() -> {
            boolean ok = painelLigado();
            h.post(() -> {
                if (ok) {
                    if (!noPainel) { noPainel = true; web.loadUrl(PAINEL); }
                    return;
                }
                if (primeira) {
                    if (!termuxInstalado()) { setup("termux"); return; }
                    if (!temPermissao()) { setup("permissao"); return; }
                    ligarPainel();
                }
                tentativas++;
                if (tentativas < 30) h.postDelayed(() -> testar(false), 700);
                else setup("naoligou");
            });
        }).start();
    }

    boolean painelLigado() {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(PAINEL + "api/tudo").openConnection();
            c.setConnectTimeout(600);
            c.setReadTimeout(4000);
            return c.getResponseCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    void setup(String motivo) {
        noPainel = false;
        web.loadUrl("file:///android_asset/setup.html#" + motivo);
    }

    boolean termuxInstalado() {
        try {
            getPackageManager().getPackageInfo(TERMUX, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    boolean temPermissao() {
        return Build.VERSION.SDK_INT < 23 ||
                checkSelfPermission("com.termux.permission.RUN_COMMAND") == PackageManager.PERMISSION_GRANTED;
    }

    /** roda um comando no Termux. fundo=true: sem abrir a tela do Termux */
    boolean termux(String comando, boolean fundo) {
        try {
            Intent i = new Intent();
            i.setClassName(TERMUX, "com.termux.app.RunCommandService");
            i.setAction("com.termux.RUN_COMMAND");
            i.putExtra("com.termux.RUN_COMMAND_PATH", BIN + "/bash");
            i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{"-lc", comando});
            i.putExtra("com.termux.RUN_COMMAND_WORKDIR", HOME);
            i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", fundo);
            i.putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0");
            startService(i);
            return true;
        } catch (Exception e) {
            Toast.makeText(this, "Não consegui falar com o Termux: " + e.getMessage(), Toast.LENGTH_LONG).show();
            return false;
        }
    }

    void ligarPainel() {
        termux("cd ~ && python ~/editor_memes/painel.py --sem-abrir > ~/.painel.log 2>&1", true);
    }

    void abrirFora(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Exception e) {
            Toast.makeText(this, "Não consegui abrir: " + url, Toast.LENGTH_SHORT).show();
        }
    }

    // ------------------------------------------------------------ ponte com o HTML
    // ------------------------------------------------------------ postar nas redes
    static final String[][] REDES = {
            {"tiktok", "com.zhiliaoapp.musically", "com.ss.android.ugc.trill"},
            {"instagram", "com.instagram.android"},
            {"youtube", "com.google.android.youtube"},
            {"facebook", "com.facebook.katana", "com.facebook.lite"},
    };

    boolean podeLerVideos() {
        String p = Build.VERSION.SDK_INT >= 33 ? "android.permission.READ_MEDIA_VIDEO" : "android.permission.READ_EXTERNAL_STORAGE";
        if (checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED) return true;
        runOnUiThread(() -> requestPermissions(new String[]{p}, 41));
        return false;
    }

    /** endereco do video na galeria (content://...), pra outro app conseguir abrir */
    Uri uriDoVideo(String caminho) {
        String[] col = {MediaStore.Video.Media._ID};
        for (int tentativa = 0; tentativa < 2; tentativa++) {
            try (Cursor c = getContentResolver().query(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, col,
                    MediaStore.Video.Media.DATA + "=?", new String[]{caminho}, null)) {
                if (c != null && c.moveToFirst()) {
                    return Uri.withAppendedPath(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, String.valueOf(c.getLong(0)));
                }
            } catch (Exception ignored) {
            }
            // ainda nao esta na galeria: pede pro Android indexar e tenta de novo
            CountDownLatch pronto = new CountDownLatch(1);
            final Uri[] achado = {null};
            MediaScannerConnection.scanFile(this, new String[]{caminho}, new String[]{"video/mp4"}, (p, uri) -> {
                achado[0] = uri;
                pronto.countDown();
            });
            try {
                pronto.await(5, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
            }
            if (achado[0] != null) return achado[0];
        }
        return null;
    }

    String postar(String caminho, String rede, String legenda) {
        if (!new File(caminho).exists()) return "Não achei o vídeo: " + caminho;
        if (!podeLerVideos()) return "Permita o acesso aos vídeos e toque de novo.";
        String pacote = null, nome = rede;
        for (String[] r : REDES) {
            if (!r[0].equals(rede)) continue;
            for (int i = 1; i < r.length; i++) {
                if (getPackageManager().getLaunchIntentForPackage(r[i]) != null) { pacote = r[i]; break; }
            }
        }
        nome = rede.equals("tiktok") ? "TikTok" : rede.equals("instagram") ? "Instagram"
                : rede.equals("youtube") ? "YouTube" : "Facebook";
        if (pacote == null) return "O " + nome + " não está instalado neste celular.";
        Uri uri = uriDoVideo(caminho);
        if (uri == null) return "O vídeo ainda não apareceu na galeria. Espere uns segundos e tente de novo.";
        final String pac = pacote;
        runOnUiThread(() -> {
            ClipboardManager cb = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cb != null && legenda != null && !legenda.isEmpty()) cb.setPrimaryClip(ClipData.newPlainText("legenda", legenda));
            Intent i = new Intent(Intent.ACTION_SEND);
            i.setType("video/mp4");
            i.putExtra(Intent.EXTRA_STREAM, uri);
            if (legenda != null && !legenda.isEmpty()) i.putExtra(Intent.EXTRA_TEXT, legenda);
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            i.setPackage(pac);
            try {
                startActivity(i);
            } catch (Exception e) {
                i.setPackage(null);
                startActivity(Intent.createChooser(i, "Postar com"));
            }
        });
        return "";
    }

    class Ponte {
        @JavascriptInterface public String postar(String caminho, String rede, String legenda) {
            return MainActivity.this.postar(caminho, rede, legenda);
        }
        @JavascriptInterface public String instalar() { return INSTALAR; }
        @JavascriptInterface public boolean termuxOk() { return termuxInstalado(); }
        @JavascriptInterface public boolean permissao() { return temPermissao(); }

        @JavascriptInterface public void copiar(String t) {
            h.post(() -> {
                ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                cm.setPrimaryClip(ClipData.newPlainText("comando", t));
                Toast.makeText(MainActivity.this, "Copiado! Cole no Termux", Toast.LENGTH_SHORT).show();
            });
        }

        @JavascriptInterface public void abrirTermux() {
            h.post(() -> {
                Intent i = getPackageManager().getLaunchIntentForPackage(TERMUX);
                if (i != null) startActivity(i);
                else abrirFora("https://f-droid.org/packages/com.termux/");
            });
        }

        @JavascriptInterface public void link(String url) { h.post(() -> abrirFora(url)); }

        @JavascriptInterface public void pedirPermissao() {
            h.post(() -> {
                if (Build.VERSION.SDK_INT >= 23)
                    requestPermissions(new String[]{"com.termux.permission.RUN_COMMAND"}, REQ_PERM);
            });
        }

        @JavascriptInterface public void tentar() { h.post(() -> iniciar()); }

        @JavascriptInterface public void atualizar() {
            h.post(() -> {
                if (temPermissao() && MainActivity.this.termux("pkill -f painel.py; " + INSTALAR + " && echo && echo 'Pronto! Volte pro app Editor Jota.' && sleep 4", false)) {
                    Toast.makeText(MainActivity.this, "Atualizando no Termux…", Toast.LENGTH_LONG).show();
                    h.postDelayed(() -> iniciar(), 4000);
                } else {
                    copiar(INSTALAR);
                    abrirTermux();
                }
            });
        }

        @JavascriptInterface public void reiniciar() {
            h.post(() -> {
                MainActivity.this.termux("pkill -f painel.py", true);
                h.postDelayed(() -> iniciar(), 1500);
            });
        }

        @JavascriptInterface public void config() { h.post(() -> setup("config")); }
        @JavascriptInterface public void voltar() { h.post(() -> iniciar()); }
    }

    // ------------------------------------------------------------ resultados
    @Override
    public void onRequestPermissionsResult(int req, String[] p, int[] r) {
        if (req == REQ_PERM) iniciar();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_ARQ && arquivoCb != null) {
            arquivoCb.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data));
            arquivoCb = null;
        } else super.onActivityResult(req, res, data);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // voltou do Termux / das permissoes: tenta de novo se estiver na tela de configuracao
        String u = web.getUrl();
        if (u != null && u.contains("setup.html") && !u.contains("#config")) h.postDelayed(() -> testar(true), 400);
    }
}

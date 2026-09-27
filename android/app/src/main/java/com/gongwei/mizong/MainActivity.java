package com.gongwei.mizong;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.KeyEvent;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * 《宫闱迷踪》的手机外壳：一屏 WebView，加载打包在 assets 里的单文件网页。
 *
 * <p>刻意只继承 {@link android.app.Activity}，不引 AndroidX：游戏全在那一份
 * assets/index.html 里（零外链、零 CDN、可离线打开），外壳要做的事情只有
 * 「把它显示出来」与「别让它去别处」。这一层越薄，手机上的行为就越等于
 * 浏览器里那一份。
 *
 * <p>assets/index.html 不是手写的：它由 {@code python tools/build_android.py} 从
 * {@code web/gongwei-mizong.html} **逐字节**拷过来（那个文件又由
 * {@code python tools/build_web.py} 从剧本打包）。所以这个类里没有任何剧情、
 * 没有任何界面代码，改玩法不必碰它。
 *
 * <p>三个刻意的「不做」：
 *
 * <ul>
 *   <li>不设 WebChromeClient 去代理 alert/confirm/prompt —— 网页里根本没有这三样
 *       对话框（提示都画在页面自己的浮层里）；
 *   <li>不设 DownloadListener —— 存档的导入导出是页面内的 textarea + 按钮，
 *       不产生下载；
 *   <li>不申请任何权限 —— 这一卷不需要网络，也不需要读写外部存储。
 * </ul>
 */
public class MainActivity extends Activity {

    /** 唯一允许加载的地址：APK 里自带的那一份单文件网页。 */
    private static final String START_URL = "file:///android_asset/index.html";

    /** 白名单前缀。除了它开头的东西，一律拦下（见 shouldOverrideUrlLoading）。 */
    private static final String ASSET_PREFIX = "file:///android_asset/";

    /** 与网页版的纸色一致（主题里的 windowBackground 也是这个），冷启动不闪白。 */
    private static final String PAPER = "#F5E6D3";

    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor(PAPER));

        WebSettings settings = webView.getSettings();
        // 界面、判定、存档全在 JS 里 —— 这两条缺一条，游戏打不开或者存不住档。
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        // 系统字号放大过的话，页面排版会跟着溢出（网页版是固定七档字号的排版合约），
        // 所以把 textZoom 钉回 100%。
        settings.setTextZoom(100);
        // 页面自己就在 APK 里（file:// 加载），所以要允许读本地文件；
        // 但**不许** file:// 的页面去读别的源 —— 离线硬保险，多一条路都不给。
        settings.setAllowFileAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);

        webView.setWebViewClient(new WebViewClient() {
            /**
             * 离线硬保险：只放行 assets 里那一份网页。
             *
             * <p>这一卷是单文件、零外链的产物（构建期就断言产物里没有 http/https），
             * 正常情况下不该有任何跳转。但 WebView 的世界里「不该」不值钱：
             * 页面上万一出现一个 http/https 链接（比如哪次改版手滑写了外链），
             * 或者谁拿 file:// 去指别处，都会被这里拦下来 —— 返回 true 就是
             * 「这次导航我接管了，WebView 什么都不做」。
             *
             * <p>页面内部的锚点跳转（file:///android_asset/index.html#xxx）仍然放行。
             */
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (request == null || request.getUrl() == null) {
                    return true;
                }
                return !request.getUrl().toString().startsWith(ASSET_PREFIX);
            }
        });

        webView.loadUrl(START_URL);
        setContentView(webView);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            // 让页面自己的计时器/动画跟着回到前台（少了这一对，切出去再回来会僵住）
            webView.onResume();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            // 切到后台就停掉页面里的活动：这一卷有落花与过场动画，不该在后台空转
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // 返回键：不拦，原样交给系统（系统按自己的规矩处理，即退出本 Activity）。
        //
        // 本来想先把返回键递给页面，让页面自己关浮层与过场。但这一卷的网页里
        // **没有** window.__gwBack 这个钩子（web/src/ui.js 里搜不到，浮层是靠
        // 屏幕上的按钮关的），而规矩是「不为了安卓去改网页源码」——
        // 所以这里如实退化成「交给系统」，而不是 evaluateJavascript 一个不存在的
        // 钩子、再假装它答应了。
        // 哪天网页真的长出那个钩子，这个方法是唯一要改的地方。
        return super.onKeyDown(keyCode, event);
    }
}

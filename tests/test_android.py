"""安卓壳的门禁：工程骨架、零权限、WebView 设置、assets 与网页产物逐字节相同。

APK 本地造不出来（这台机器上没有 Android SDK、没有模拟器、没有 gradle），所以这条
流水线守的不是「跑起来对不对」，而是**能被静态读出来的那部分合约**：

1. **骨架**：Gradle 工程该有的文件都在，而且**没有** wrapper（wrapper 是二进制，
   不提交；CI 用 `gradle/actions/setup-gradle` 装的 gradle）。
2. **壳子**：包名、minSdk、WebView 的开关、assets 的加载地址、返回键为什么没拦。
3. **零权限**：清单里一条 `<uses-permission>` 都不许有 —— 这一卷全在本地
   （网页在 assets 里、存档在 localStorage），`android.yml` 还会用 aapt2 拆开
   产物再复核一遍「没有 INTERNET」。
4. **零依赖**：`dependencies {}` 必须是空的；工作流只许用官方/维护方的一手 action。
5. **搬运工**：`tools/build_android.py` 在 assets 缺失/不一致时必须红、在网页产物
   自己陈旧时绝不动 assets、一致时必须逐字节相同。这一条用临时目录打桩跑，
   不碰真仓库里的文件（assets 是生成物，仓库里本来就没有）。

最后一条特别重要：`android/app/src/main/assets/index.html` 被 `.gitignore` 忽略，
`gates.yml` 也不跑 `tools/build_android.py` —— 所以**这条测试不许假设它存在**。
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ANDROID = ROOT / "android"
APP = ANDROID / "app"
MAIN = APP / "src" / "main"
MANIFEST = MAIN / "AndroidManifest.xml"
JAVA_DIR = MAIN / "java" / "com" / "gongwei" / "mizong"
ACTIVITY = JAVA_DIR / "MainActivity.java"
RES = MAIN / "res"
ASSET = MAIN / "assets" / "index.html"
WEB_HTML = ROOT / "web" / "gongwei-mizong.html"
WORKFLOW = ROOT / ".github" / "workflows" / "android.yml"
GITIGNORE = ROOT / ".gitignore"

APP_ID = "com.gongwei.mizong"
MIN_SDK = 24
TARGET_SDK = 34

#: 启动界面要引的资源（少一个就是编译期红，越早说越好）。
SKELETON = (
    ANDROID / "settings.gradle",
    ANDROID / "build.gradle",
    ANDROID / "gradle.properties",
    APP / "build.gradle",
    MANIFEST,
    ACTIVITY,
    RES / "values" / "strings.xml",
    RES / "values" / "themes.xml",
    RES / "values" / "ic_launcher_background.xml",
    RES / "drawable" / "ic_launcher.xml",
    RES / "mipmap-anydpi-v26" / "ic_launcher.xml",
)

#: 矢量图里许出现的属性：这几样 API 21 起就认，24 上稳。
VECTOR_ATTRS = {
    "width", "height", "viewportWidth", "viewportHeight",
    "pathData", "fillColor", "strokeColor", "strokeWidth",
}

#: 工作流只许用这些来源的 action（官方 / 维护方一手）。
ACTION_OWNERS = ("actions/", "android-actions/", "gradle/")


def load_tool(name: str):
    """把 tools/ 下的脚本当模块载入（共用 ``tests.helpers.load_tool``）。"""
    from .helpers import load_tool as _load_tool

    return _load_tool(name)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def braced(text: str, header: str) -> str:
    """取出 ``header {`` 到配对 ``}`` 之间的正文（够用就好的括号配平）。"""
    start = text.find(header)
    if start < 0:
        raise AssertionError(f"没找到 {header!r}")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise AssertionError(f"{header!r} 的花括号没有配平")


JAVA_STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def code_only(text: str) -> str:
    """去掉注释，只留代码。

    注释里会大写写着「不引 AndroidX」「不设 WebChromeClient」，
    拿原始文本做否定断言会被自己的注释绊倒；而字符串里的 ``file://``
    又会把 ``//`` 注释规则带偏，所以先把字符串抠出来再剥注释。
    """
    strings = []

    def stash(match):
        strings.append(match.group(0))
        return f"\x00{len(strings) - 1}\x00"

    text = JAVA_STRING.sub(stash, text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], text)


def yaml_code(text: str) -> str:
    """去掉整行注释的 YAML（开头的说明里会出现 ``#``，别把它当配置读）。"""
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


def xml_only(text: str) -> str:
    """去掉 XML 注释的正文。

    注释里会理直气壮地写着「不许出现 <uses-permission>」「刻意不用 aapt:attr」，
    拿整份文件做否定断言，等于让注释把自己绊倒。
    """
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


class SkeletonTest(unittest.TestCase):
    """工程骨架：该在的都在，不该在的一个也没有。"""

    def test_骨架文件都在且非空(self):
        missing = [p.relative_to(ROOT).as_posix() for p in SKELETON
                   if not p.is_file() or not p.read_bytes().strip()]
        self.assertEqual([], missing, "安卓工程缺文件：\n  " + "\n  ".join(missing))

    def test_没有_gradle_wrapper_也没有二进制(self):
        """wrapper 的 jar 是二进制，不进版本库；CI 用 setup-gradle 装的 gradle。"""
        strays = [p.relative_to(ROOT).as_posix()
                  for p in ANDROID.rglob("*")
                  if p.is_file() and (p.suffix == ".jar" or p.name.startswith("gradlew"))]
        self.assertEqual([], strays, "不该提交的 gradle wrapper：\n  " + "\n  ".join(strays))
        self.assertFalse((ANDROID / "gradle" / "wrapper").exists())

    def test_源码目录就是AGP默认的src_main_java(self):
        self.assertTrue(ACTIVITY.is_file())
        self.assertIn("package " + APP_ID + ";", read(ACTIVITY))
        self.assertNotIn("sourceSets", code_only(read(APP / "build.gradle")),
                         "源码放在默认目录里，别另开 sourceSets")


class GradleConfigTest(unittest.TestCase):
    """Gradle 侧：包名、SDK 级别、零依赖。"""

    def test_包名与_SDK_级别(self):
        app = code_only(read(APP / "build.gradle"))
        self.assertIn(f"namespace '{APP_ID}'", app)
        self.assertIn(f"applicationId '{APP_ID}'", app)
        self.assertIn(f"minSdk {MIN_SDK}", app)
        self.assertIn("compileSdk 34", app)
        self.assertIn("targetSdk 34", app)
        self.assertIn("versionCode 1", app)
        self.assertIn("versionName '1.0'", app)

    def test_Java_17_与不混淆的_release(self):
        app = code_only(read(APP / "build.gradle"))
        self.assertIn("sourceCompatibility JavaVersion.VERSION_17", app)
        self.assertIn("targetCompatibility JavaVersion.VERSION_17", app)
        release = braced(app, "release {")
        self.assertIn("minifyEnabled false", release)

    def test_dependencies_是空的(self):
        """零第三方依赖是硬红线：写下一行 implementation 就会在这里红。"""
        body = braced(code_only(read(APP / "build.gradle")), "dependencies {")
        lines = [line.strip() for line in body.splitlines()
                 if line.strip() and line.strip() not in ("dependencies {", "}")]
        self.assertEqual([], lines, "app/build.gradle 的 dependencies 必须是空块：\n  "
                         + "\n  ".join(lines))
        self.assertNotIn("androidx", code_only(read(ACTIVITY)).lower())

    def test_根工程只声明插件版本(self):
        root = read(ANDROID / "build.gradle")
        self.assertIn("id 'com.android.application' version '8.5.2' apply false", root)
        self.assertNotIn("8.5.2'", read(APP / "build.gradle"),
                         "版本只在根工程写一次，模块里不要再写")

    def test_settings_只认两个仓库(self):
        text = read(ANDROID / "settings.gradle")
        self.assertIn("pluginManagement {", text)
        self.assertIn("RepositoriesMode.FAIL_ON_PROJECT_REPOS", text)
        self.assertIn("google()", text)
        self.assertIn("mavenCentral()", text)
        self.assertIn("rootProject.name = 'gongwei-mizong'", text)
        self.assertIn("include ':app'", text)

    def test_gradle_properties_两个开关(self):
        text = read(ANDROID / "gradle.properties")
        self.assertIn("org.gradle.jvmargs=-Xmx2g", text)
        self.assertIn("android.useAndroidX=false", text)


class ManifestTest(unittest.TestCase):
    """清单：一条权限都不许有，明文流量不许开。"""

    def setUp(self):
        self.text = read(MANIFEST)
        self.code = xml_only(self.text)

    def test_一条_uses_permission_都没有(self):
        self.assertNotIn("<uses-permission", self.code)
        self.assertNotIn("android.permission", self.code)

    def test_离线与备份开关(self):
        self.assertIn('android:usesCleartextTraffic="false"', self.code)
        self.assertIn('android:allowBackup="true"', self.code)
        self.assertIn('android:hardwareAccelerated="true"', self.code)

    def test_启动界面引的资源都在(self):
        for token in ('android:label="@string/app_name"',
                      'android:icon="@drawable/ic_launcher"',
                      'android:roundIcon="@drawable/ic_launcher"',
                      'android:theme="@style/AppTheme"'):
            self.assertIn(token, self.code)

    def test_Activity_的四个属性与_LAUNCHER(self):
        activity = self.code[self.code.index("<activity"):]
        self.assertIn('android:name=".MainActivity"', activity)
        self.assertIn('android:exported="true"', activity)
        self.assertIn('android:windowSoftInputMode="adjustResize"', activity)
        for flag in ("orientation", "screenSize", "screenLayout", "keyboardHidden",
                     "uiMode", "density", "fontScale"):
            self.assertIn(flag, activity,
                          f"configChanges 少了 {flag}：重建会让 WebView 重新加载")
        self.assertIn('android:name="android.intent.action.MAIN"', activity)
        self.assertIn('android:name="android.intent.category.LAUNCHER"', activity)


class WebViewShellTest(unittest.TestCase):
    """MainActivity：开什么、关什么、从哪儿加载。"""

    def setUp(self):
        self.code = code_only(read(ACTIVITY))

    def test_两个救命开关都开着(self):
        self.assertIn("setJavaScriptEnabled(true)", self.code)
        self.assertIn("setDomStorageEnabled(true)", self.code)  # 存档靠 localStorage

    def test_字号与本地文件(self):
        self.assertIn("setTextZoom(100)", self.code)
        self.assertIn("setAllowFileAccess(true)", self.code)
        self.assertIn("setAllowFileAccessFromFileURLs(false)", self.code)
        self.assertIn("setAllowUniversalAccessFromFileURLs(false)", self.code)

    def test_加载地址就是_assets_里那一份(self):
        # 加载地址里的文件名必须与搬进 assets 的那份对得上（index.html）
        self.assertIn(f'"file:///android_asset/{ASSET.name}"', self.code)
        self.assertIn("loadUrl(START_URL)", self.code)
        self.assertIn("setContentView(webView)", self.code)

    def test_非_assets_的跳转一律拦掉(self):
        self.assertIn('ASSET_PREFIX = "file:///android_asset/"', self.code)
        self.assertIn("startsWith(ASSET_PREFIX)", self.code)
        self.assertIn("shouldOverrideUrlLoading", self.code)

    def test_返回键如实交给系统且没有假钩子(self):
        """网页里没有 ``window.__gwBack``，所以这里不许假装有。

        反过来也成立：哪天网页真的长出那个钩子，这条会红 —— 那时该做的是
        去 ``onKeyDown`` 里把返回键递给页面，并把这条断言改成正着测。
        """
        ui_js = read(ROOT / "web" / "src" / "ui.js")
        self.assertNotIn("__gwBack", ui_js,
                         "网页长出 __gwBack 了：去 MainActivity.onKeyDown 接上它")
        self.assertNotIn("evaluateJavascript(", self.code)
        self.assertIn("return super.onKeyDown(keyCode, event);", self.code)

    def test_前后台跟着停走(self):
        self.assertIn("webView.onResume();", self.code)
        self.assertIn("webView.onPause();", self.code)

    def test_只用系统的_Activity(self):
        self.assertIn("import android.app.Activity;", self.code)
        self.assertIn("extends Activity", self.code)
        self.assertNotIn("WebChromeClient", self.code,
                         "网页里没有 alert/confirm/prompt，不需要对话框代理")
        self.assertNotIn("DownloadListener", self.code)


class ResourcesTest(unittest.TestCase):
    """资源：名字、纸色主题、能被 API 24 渲染的矢量图标。"""

    def test_应用名(self):
        self.assertIn('<string name="app_name">宫闱迷踪</string>',
                      read(RES / "values" / "strings.xml"))

    def test_主题用系统_Material_且纸色一致(self):
        text = read(RES / "values" / "themes.xml")
        self.assertIn('<style name="AppTheme" parent="android:Theme.Material.Light.NoActionBar">',
                      text)
        self.assertIn('<item name="android:statusBarColor">#F5E6D3</item>', text)
        self.assertIn('<item name="android:navigationBarColor">#F5E6D3</item>', text)
        self.assertIn('<item name="android:windowBackground">#F5E6D3</item>', text)
        self.assertIn('<item name="android:windowLightStatusBar">true</item>', text)

    def test_矢量图标只用_API24_认的属性(self):
        text = xml_only(read(RES / "drawable" / "ic_launcher.xml"))
        self.assertIn("<vector", text)
        self.assertIn("#8C2B2B", text)
        self.assertNotIn("aapt:", text, "aapt:attr 要额外命名空间，别用")
        attrs = set(re.findall(r"android:([A-Za-z]+)=", text))
        self.assertEqual(set(), attrs - VECTOR_ATTRS,
                         "矢量图里出现了老渲染路径不认的属性：" + "、".join(sorted(attrs - VECTOR_ATTRS)))
        for token in ("fillColor", "strokeColor", "pathData"):
            self.assertIn(token, text)

    def test_自适应图标引前景与底色(self):
        text = read(RES / "mipmap-anydpi-v26" / "ic_launcher.xml")
        self.assertIn("<adaptive-icon", text)
        self.assertIn('android:drawable="@color/ic_launcher_background"', text)
        self.assertIn('android:drawable="@drawable/ic_launcher"', text)
        self.assertIn('<color name="ic_launcher_background">#8C2B2B</color>',
                      read(RES / "values" / "ic_launcher_background.xml"))


class AssetToolTest(unittest.TestCase):
    """搬运工本身也要被验：它说「一致」的时候，必须真的逐字节一致。"""

    def setUp(self):
        self.tool = load_tool("build_android")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.web = Path(tmp.name) / "gongwei-mizong.html"
        self.asset = Path(tmp.name) / "assets" / "index.html"

    def _patched(self, body: bytes, *, stale: bool = False):
        """把两个路径都指到临时目录，并给 build_web 打桩。

        ``stale=True`` 时打桩的 build() 交回一份**与磁盘不同**的产物，
        用来验「网页自己陈旧就绝不动 assets」。
        """
        self.web.write_bytes(body)
        returned = body.decode("utf-8") + ("<!-- 陈旧 -->" if stale else "")

        class _FakeBuildWeb:
            @staticmethod
            def build():
                return {self.web: returned}

        return (
            mock.patch.object(self.tool, "WEB_HTML", self.web),
            mock.patch.object(self.tool, "ASSET_HTML", self.asset),
            mock.patch.object(self.tool, "_load_build_web", lambda: _FakeBuildWeb),
        )

    def _run(self, argv, body: bytes, *, stale: bool = False):
        out, err = io.StringIO(), io.StringIO()
        patches = self._patched(body, stale=stale)
        with patches[0], patches[1], patches[2]:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.tool.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_check_缺_assets_返回非零并给出提示(self):
        body = b"<html>game</html>"
        code, _, err = self._run(["--check"], body)
        self.assertEqual(1, code)
        self.assertIn("不存在", err)
        self.assertIn(self.tool.REBUILD_HINT, err)
        self.assertFalse(self.asset.exists(), "--check 不许写盘")

    def test_check_一致时返回零(self):
        body = b"<html>game</html>"
        self.asset.parent.mkdir(parents=True, exist_ok=True)
        self.asset.write_bytes(body)
        code, out, err = self._run(["--check"], body)
        self.assertEqual(0, code, err)
        self.assertIn("是最新的", out)
        self.assertIn(f"（{len(body)} 字节）", out)

    def test_check_差一个字节就红(self):
        body = b"<html>game</html>"
        self.asset.parent.mkdir(parents=True, exist_ok=True)
        self.asset.write_bytes(body[:-1] + b"!")
        code, _, err = self._run(["--check"], body)
        self.assertEqual(1, code)
        self.assertIn("不一致", err)
        self.assertIn(self.tool.REBUILD_HINT, err)

    def test_默认模式逐字节拷贝(self):
        # 故意带上非 ASCII、裸字节与不规则的换行：拷贝必须是「原样」而不是「读懂再写回」
        body = "<html>\r\n  <p>宫闱迷踪</p>\n</html>\n".encode("utf-8") + b"\xe4\xb8\x80"
        code, out, err = self._run([], body)
        self.assertEqual(0, code, err)
        self.assertTrue(self.asset.is_file())
        self.assertEqual(body, self.asset.read_bytes())
        self.assertIn("✓ 写出", out)
        self.assertIn(f"（{len(body)} 字节）", out)

    def test_网页产物陈旧时绝不动_assets(self):
        body = b"<html>game</html>"
        self.asset.parent.mkdir(parents=True, exist_ok=True)
        self.asset.write_bytes(b"old")
        code, out, err = self._run([], body, stale=True)
        self.assertEqual(1, code)
        self.assertIn("不一致", err)
        self.assertIn(self.tool.REBUILD_HINT, err)
        self.assertEqual(b"old", self.asset.read_bytes(), "陈旧产物绝不许进 APK")
        self.assertNotIn("✓ 写出", out)

    def test_真仓库的网页产物不陈旧(self):
        """真跑一次：磁盘上的 web/gongwei-mizong.html 等于当前剧本打的包。

        这本来是 ``tools/build_web.py --check`` 自己的门禁（AGENTS §4 第一条），
        这里再核一遍，是为了保证搬进 APK 的不是一盘旧菜。仓库里改了剧本还没重新
        打包时它会红，而修法（跑 build_web）不在本任务的改动范围里 —— 所以只报
        出一句可执行的提示，不把别人的红算成这条流水线的红。
        """
        problems = self.tool.web_problems()
        if problems:
            self.skipTest("网页产物当前是陈旧的，先跑 python tools/build_web.py："
                          + "；".join(problems))
        self.assertEqual([], problems)

    def test_真仓库里搬过的话必须逐字节一致(self):
        """assets 是生成物（被 .gitignore 挡着、仓库里没有），本地搬过之后才验。"""
        if ASSET.exists():
            self.assertEqual(WEB_HTML.read_bytes(), ASSET.read_bytes())


class WorkflowTest(unittest.TestCase):
    """工作流：顺序、action 来源、以及那条真验证。"""

    def setUp(self):
        self.text = read(WORKFLOW)
        self.code = yaml_code(self.text)

    def test_触发条件与权限(self):
        self.assertTrue(self.code.startswith("name: android"))
        self.assertIn("branches: [main]", self.text)
        self.assertIn("tags: ['v*']", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertIn("pull_request:", self.text)
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: write", self.text)
        self.assertIn("concurrency:", self.text)
        self.assertIn("cancel-in-progress: true", self.text)

    def test_单腿与超时(self):
        self.assertIn("runs-on: ubuntu-latest", self.text)
        self.assertIn("timeout-minutes: 30", self.text)
        self.assertNotIn("windows-latest", self.text, "APK 只在 Linux 上打一次就够")

    def test_只用一手_action(self):
        used = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", self.code, flags=re.M)
        self.assertTrue(used)
        strangers = [u for u in used if not u.startswith(ACTION_OWNERS)]
        self.assertEqual([], strangers, "不许用第三方 action：\n  " + "\n  ".join(strangers))
        # 注释里会聊到「不用 softprops」——只许在注释里出现，不许真的 uses 它
        self.assertNotIn("softprops", self.code.lower())
        self.assertIn("actions/upload-artifact@v", self.code)
        # 每个 action 都要钉大版本号（不许 @main 这种漂移写法），但具体数字不写进断言：
        # GitHub 每升一档大版本就要改测试，不值当——真正要守的是「钉住」这件事。
        unpinned = [u for u in used if not re.search(r"@v\d+$", u)]
        self.assertEqual([], unpinned, "action 必须钉大版本号：\n  " + "\n  ".join(unpinned))

    def test_先把网页搬进来再编译(self):
        web = self.code.index("python tools/build_web.py")
        move = self.code.index("python tools/build_android.py")
        check = self.code.index("python tools/build_android.py --check")
        build = self.code.index("assembleDebug")
        self.assertLess(web, move, "先打包网页，再搬进 assets")
        self.assertLess(move, check, "先搬，再复核")
        self.assertLess(check, build, "复核通过才编译")
        self.assertIn("gradle -p android assembleDebug --no-daemon", self.code)

    def test_拆开_APK_验包名与_sdk(self):
        """aapt2 打的标签是 ``minSdkVersion`` / ``targetSdkVersion``。

        2026-09-27 第一次真跑这条流水线时，断言写的是老 ``aapt`` 的 ``sdkVersion:'24'``，
        于是 APK 明明是对的、流水线照样红在最后一步 —— 这条测试就是要钉住标签名，
        别让人再照抄旧写法。
        """
        self.assertIn("aapt2", self.code)
        self.assertIn("dump badging", self.code)
        self.assertIn(f'"package: name=\'{APP_ID}\'"', self.code)
        self.assertIn(f'"minSdkVersion:\'{MIN_SDK}\'"', self.code)
        self.assertIn(f'"targetSdkVersion:\'{TARGET_SDK}\'"', self.code)
        self.assertNotIn("sdkVersion:'24'", self.code.replace("minSdkVersion:'24'", ""))

    def test_真验证里钉着不许联网(self):
        """这条断言必须落在 ``run:`` 里（注释不算）。"""
        self.assertIn("android.permission.INTERNET", self.code)
        self.assertIn('SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:', self.code)
        self.assertIn('find "$SDK/build-tools"', self.code)
        self.assertIn("exit 1", self.code)

    def test_产物与_Release(self):
        self.assertIn("name: gongwei-mizong-debug-apk", self.code)
        self.assertIn("android/app/build/outputs/apk/debug/app-debug.apk", self.code)
        self.assertIn("if-no-files-found: error", self.code)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", self.code)
        self.assertIn("secrets.GITHUB_TOKEN", self.code)
        self.assertIn("gh release", self.code)
        self.assertNotIn("gradle wrapper", self.text.lower())
        self.assertNotIn("gradlew", self.text)


class GitignoreTest(unittest.TestCase):
    """生成物不进版本库。"""

    def test_assets_被忽略(self):
        lines = [line.strip() for line in read(GITIGNORE).splitlines()]
        self.assertIn("android/app/src/main/assets/index.html", lines)
        self.assertEqual("android/app/src/main/assets/index.html",
                         ASSET.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    unittest.main(verbosity=2)

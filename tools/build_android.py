"""把单文件网页搬进安卓工程的 assets，让 APK 里的页面与 `web/` 那一份逐字节相同。

    python tools/build_android.py            # 刷新 android/app/src/main/assets/index.html
    python tools/build_android.py --check    # 只检查磁盘上那份是不是最新的，不写盘

为什么要有这个脚本：安卓壳子加载的就是 `assets/index.html`，而真正的产物是
`tools/build_web.py` 打出来的 `web/gongwei-mizong.html`。两者必须是**同一串字节**
——否则「网页修好了、装到手机上还是旧的」这种事只有在真机上才看得出来。
所以这里不做任何加工：原样拷贝，编码、行尾、内联脚本一个字节都不动
（也正因为它是生成物，`.gitignore` 里那一行把它挡在版本库外）。

拷贝前先拿 `tools/build_web.py` 的 `build()` 与磁盘上的产物比一次：**网页产物
自己陈旧时直接失败**，免得把一份过期的剧本打进 APK。这把尺子与
`python tools/build_web.py --check` 是同一把 —— 同一个 `build()`，同一份内容包。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，打印「✓」会炸；统一按 UTF-8 输出。
from gongwei.console import use_utf8  # noqa: E402

use_utf8()

WEB_HTML = ROOT / "web" / "gongwei-mizong.html"
ASSET_DIR = ROOT / "android" / "app" / "src" / "main" / "assets"
ASSET_HTML = ASSET_DIR / "index.html"
BUILD_WEB = ROOT / "tools" / "build_web.py"

#: 出问题时给的那一句（照着敲就行，顺序也说明了谁先谁后）。
REBUILD_HINT = "先跑 python tools/build_web.py 与 tools/build_android.py"


def _rel(path: Path) -> str:
    """打印用的相对路径；临时目录里的路径（测试用）照原样显示。"""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _load_build_web():
    """把 `tools/build_web.py` 当模块载入（tools 不是包），借用它那把尺子。"""
    spec = importlib.util.spec_from_file_location("_tool_build_web", BUILD_WEB)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def web_problems() -> List[str]:
    """网页产物是不是陈旧的：拿 build_web.build() 的结果与磁盘逐字节比对。

    与 `python tools/build_web.py --check` 同一把尺子（同一个 build()）。
    按字节比而不是按文本比：仓库锁 LF、产物按字节比对，文本读法会把行尾的
    差异悄悄吃掉，而打进 APK 的正是字节。
    """
    problems: List[str] = []
    for path, text in _load_build_web().build().items():
        rel = _rel(path)
        if not path.exists():
            problems.append(f"{rel} 不存在")
        elif path.read_bytes() != text.encode("utf-8"):
            problems.append(f"{rel} 与当前剧本不一致")
    return problems


def build() -> Dict[Path, bytes]:
    """返回 {输出路径: 字节}；不写盘，便于测试与 --check 复用。

    只有一份输出：assets 里的 `index.html`，内容就是网页产物的原始字节。
    """
    return {ASSET_HTML: WEB_HTML.read_bytes()}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把单文件网页搬进安卓 assets（逐字节）")
    ap.add_argument("--check", action="store_true",
                    help="只比对网页产物与 assets 是否逐字节相同，不写盘")
    args = ap.parse_args(argv)

    # 第一步永远先问「网页那一份是不是最新的」：陈旧的产物不许进 APK。
    problems = web_problems()
    if problems:
        for line in problems:
            print(f"✗ {line}（{REBUILD_HINT}）", file=sys.stderr)
        return 1

    for path, data in build().items():
        rel = _rel(path)
        size = len(data)
        if args.check:
            current = path.read_bytes() if path.exists() else None
            if current is None:
                problems.append(f"{rel} 不存在（{REBUILD_HINT}）")
            elif current != data:
                problems.append(f"{rel} 与 web/gongwei-mizong.html 不一致（{REBUILD_HINT}）")
            else:
                print(f"✓ {rel} 是最新的（{size} 字节）")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        # 逐字节写：assets 那份必须与网页产物完全一致（不许有平台的换行翻译）。
        path.write_bytes(data)
        print(f"✓ 写出 {rel}（{size} 字节）")

    if problems:
        for line in problems:
            print(f"✗ {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

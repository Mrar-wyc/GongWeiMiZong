"""把剧本、引擎与界面打成一个自包含的单文件网页。

    python tools/build_web.py            # 重新生成 web/gongwei-mizong.html
    python tools/build_web.py --check    # 只检查磁盘上的那份是不是最新的

为什么要打包成一个文件：这一卷要能**双击就玩**、能丢进手机、能离线打开，
所以不允许任何外部请求（没有 CDN、没有字体、没有图片文件）。构建时会断言
产物里不含 http/https 引用；带上一点点资源就会在这里失败，而不是在用户
断网时静默崩掉。

产出两份：
  web/gongwei-mizong.html   单文件游戏（剧本内联在里面）
  web/gongwei-pack.json     同一份内容包，供 web/src/driver.js 与门禁使用

内容包只由 `gongwei/web/pack.py` 生成 —— 网页端不许有第二份剧本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，打印「✓」会炸；统一按 UTF-8 输出（包入口也会做一次）。
from gongwei.console import use_utf8  # noqa: E402

use_utf8()

from gongwei.data.story import TOPIC_GATES, build_content  # noqa: E402
from gongwei.web.pack import content_pack, pack_json  # noqa: E402

SHELL = ROOT / "web" / "shell.html"
SRC_DIR = ROOT / "web" / "src"
OUT_HTML = ROOT / "web" / "gongwei-mizong.html"
OUT_PACK = ROOT / "web" / "gongwei-pack.json"

PACK_PLACEHOLDER = "__PACK__"
STYLE_PLACEHOLDER = "__STYLE__"
GAME_PLACEHOLDER = "__GAME_JS__"
UI_PLACEHOLDER = "__UI_JS__"

EXT_PATTERNS = ("http://", "https://", "//cdn.", "src=\"/", "href=\"/")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _guard(name: str, text: str) -> None:
    """把会在浏览器里咬人的东西挡在构建期。"""
    lower = text.lower()
    for token in EXT_PATTERNS:
        if token in lower:
            raise SystemExit(f"{name} 里有外部引用 {token!r}：这一卷必须能离线打开")
    for token in ("</script", "<script"):
        if token in lower:
            raise SystemExit(f"{name} 里出现了 {token!r}：内联时会截断页面")
    if PACK_PLACEHOLDER in text or STYLE_PLACEHOLDER in text:
        raise SystemExit(f"{name} 里残留了占位符 {PACK_PLACEHOLDER!r}")


def build() -> Dict[Path, str]:
    """返回 {输出路径: 文本}；不写盘，便于测试与 --check 复用。"""
    content = build_content()
    pack = pack_json(content, TOPIC_GATES)
    style = _read(SRC_DIR / "style.css")
    game_js = _read(SRC_DIR / "game.js")
    ui_js = _read(SRC_DIR / "ui.js")
    shell = _read(SHELL)

    _guard("style.css", style)
    _guard("game.js", game_js)
    _guard("ui.js", ui_js)
    # 内容包是 JSON，只挡掉会截断 <script> 的序列
    if "</script" in pack.lower():
        raise SystemExit("内容包里有 </script：内联时会截断页面")
    pack = pack.replace("<\\/", "</")  # 允许 JSON 里写 <\/ 的转义形态

    html = shell
    for placeholder, text in ((STYLE_PLACEHOLDER, style),
                              (PACK_PLACEHOLDER, pack),
                              (GAME_PLACEHOLDER, game_js),
                              (UI_PLACEHOLDER, ui_js)):
        if placeholder not in html:
            raise SystemExit(f"web/shell.html 里缺少占位符 {placeholder}")
        html = html.replace(placeholder, text)
    if PACK_PLACEHOLDER in html or STYLE_PLACEHOLDER in html:
        raise SystemExit("生成结果里还残留占位符")

    pretty = json.dumps(content_pack(content, TOPIC_GATES), ensure_ascii=False,
                        sort_keys=True, indent=1)
    return {OUT_HTML: html, OUT_PACK: pretty + "\n"}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包单文件网页（剧本内联）")
    ap.add_argument("--check", action="store_true",
                    help="只比对磁盘上的产物是否与当前剧本一致，不写盘")
    args = ap.parse_args(argv)

    outputs = build()
    problems: List[str] = []
    for path, text in outputs.items():
        rel = path.relative_to(ROOT).as_posix()
        size = len(text.encode("utf-8"))
        if args.check:
            current = _read(path) if path.exists() else None
            if current is None:
                problems.append(f"{rel} 不存在")
            elif current != text:
                problems.append(f"{rel} 与当前剧本不一致（请重新运行 tools/build_web.py）")
            else:
                print(f"✓ {rel} 是最新的（{size} 字节）")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        # 固定 LF：产物是要交给浏览器与手机的文件，行尾不该随平台漂移
        # （也免得「写出 N 字节」与磁盘上的实际大小对不上）。
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print(f"✓ 写出 {rel}（{size} 字节）")

    if problems:
        for line in problems:
            print(f"✗ {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

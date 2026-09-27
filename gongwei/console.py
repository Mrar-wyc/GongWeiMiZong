"""控制台输出的小事：让中文与「✓」在 Windows 上也能打印。

Windows 的默认控制台编码是 GBK，`print("✓ …")` 会直接
`UnicodeEncodeError: 'gbk' codec can't encode character '\\u2713'` —— 一个纯
显示问题却会把体检脚本整个打断。这里把两个流改成 UTF-8（改不动就算了，
毕竟这不是脚本该管的事）。

包入口会调用一次；工具脚本自己再调也无妨（幂等）。
"""

from __future__ import annotations

import sys


def use_utf8() -> None:
    """把 stdout/stderr 切到 UTF-8；不支持 reconfigure 的环境安静地跳过。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # 已经关了、或者是被重定向的奇怪对象
            pass

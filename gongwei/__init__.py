"""宫闱迷踪 · 终端探案 —— 包入口。"""

from .console import use_utf8 as _use_utf8

# 这一步是给 Windows 控制台兜底的：默认 GBK 打不出「✓」，体检脚本会因此崩掉。
# 放在包入口，任何入口（main.py / tools/*.py / 测试）都不会漏。
_use_utf8()

__all__ = ["__version__"]

__version__ = "1.0.0"

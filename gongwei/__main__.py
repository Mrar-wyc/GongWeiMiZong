"""`python -m gongwei` 入口 —— 与 `python main.py` 等价。"""

from __future__ import annotations

import sys


def main(argv=None) -> int:
    here = __import__("os").path.dirname(
        __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    from main import main as _main
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

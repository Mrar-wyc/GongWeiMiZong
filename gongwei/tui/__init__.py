"""终端 UI 层：排版原语、画布、终端会话。"""

from .terminal import (  # noqa: F401
    App,
    Canvas,
    QuitApp,
    Rect,
    Terminal,
    char_width,
    display_width,
    paint,
    pad,
    read_key,
    split_columns,
    strip_ansi,
    truncate,
    visible_width,
    wrap_text,
)

__all__ = [
    "App",
    "Canvas",
    "QuitApp",
    "Rect",
    "Terminal",
    "char_width",
    "display_width",
    "paint",
    "pad",
    "read_key",
    "split_columns",
    "strip_ansi",
    "truncate",
    "visible_width",
    "wrap_text",
]

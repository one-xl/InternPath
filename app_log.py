"""
站点运行日志：追加写入项目目录下 logs/internpath_site.log，供排障与审计。
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import Config

_LOGGER = logging.getLogger("internpath.site")
_INITIALIZED = False


def setup_site_logging() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True
    log_dir = Path(Config.BASE_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "internpath_site.log"
    _LOGGER.setLevel(logging.INFO)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(fh)
    _LOGGER.propagate = False
    _LOGGER.info("site_logging_ready | path=%s", path)


def log_site_event(event: str, detail: str = "") -> None:
    setup_site_logging()
    if detail:
        _LOGGER.info("%s | %s", event, detail[:4000])
    else:
        _LOGGER.info("%s", event)


def log_site_error(event: str, detail: str = "") -> None:
    setup_site_logging()
    _LOGGER.error("%s | %s", event, (detail or "")[:4000])


def read_site_log_tail(max_lines: int = 250) -> str:
    path = Path(Config.BASE_DIR) / "logs" / "internpath_site.log"
    if not path.is_file():
        return "（尚无日志文件；完成一次操作后会自动生成。）"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"（读取日志失败：{exc}）"
    lines = text.splitlines()
    tail = lines[-max_lines:]
    return "\n".join(tail) if tail else "（日志文件为空）"

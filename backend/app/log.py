"""日志体系：控制台输出 + 按天滚动的文件日志，用于留痕与排障。

- 文件：logs/app.log，每天零点自动滚动，保留最近 7 天
- 级别：由配置 settings.log_level 控制，生产环境可调高避免多余日志
- uvicorn 自带日志统一收敛到根 logger，避免控制台重复输出
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

from .config import settings

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
_initialized = False


def _setup() -> None:
    """初始化根 logger 的处理器（进程内只执行一次）。"""
    global _initialized
    if _initialized:
        return

    os.makedirs(settings.log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()  # 避免重复添加

    # 文件处理器：按天滚动，保留 7 天
    file_handler = TimedRotatingFileHandler(
        os.path.join(settings.log_dir, "app.log"),
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file_handler)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(console_handler)

    # uvicorn 日志统一交给根 logger 处理，避免控制台重复打印
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True

    _initialized = True


def get_logger(name: str = "app") -> logging.Logger:
    """获取应用日志器，首次调用时自动完成日志初始化。"""
    _setup()
    return logging.getLogger(name)

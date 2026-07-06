"""
日志工具模块
统一配置日志格式，输出到控制台和滚动文件
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(level: str = "INFO", log_dir: str = "") -> logging.Logger:
    """
    初始化全局 logger。
    - 控制台输出彩色简短日志
    - 文件输出详细日志，最大 5MB，保留 3 个备份
    log_dir 未指定时自动使用 data_path("data")，指向可写数据目录（打包后为 exe 同目录）。
    """
    if not log_dir:
        try:
            from app.app_context import data_path
            log_dir = data_path("data")
        except Exception:
            log_dir = "data"

    log_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger("tutu")
    logger.setLevel(log_level)

    # 避免重复添加 handler；但始终更新 level（允许运行时从 config 覆盖默认 INFO）
    if logger.handlers:
        for h in logger.handlers:
            h.setLevel(log_level)
        return logger

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # 文件 handler
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger

"""
Yuuki Bot Core Module
结城希亚核心模块
"""

__version__ = "2.5.0"
__author__ = "Yuuki Noa"
__description__ = "玖方女学院2年生，瓦尔哈拉社领导人"

# 导出核心组件
from . import config
from . import utils
from .core import *

__all__ = [
    "config",
    "utils",
    "__version__",
    "__author__",
    "__description__",
]
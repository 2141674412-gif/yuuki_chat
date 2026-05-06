"""
工具函数模块
提供通用的工具函数
"""

import os
import json
import hashlib
import httpx
import asyncio
from typing import Any, Dict, List, Optional


def safe_int(value, default=0):
    """安全转换整数"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default=0.0):
    """安全转换浮点数"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def calc_sha256(data: bytes) -> str:
    """计算 SHA256 哈希值"""
    return hashlib.sha256(data).hexdigest()


def calc_file_hash(filepath: str) -> str:
    """计算文件的 SHA256 哈希值"""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def load_json(filepath: str, default: Any = None) -> Any:
    """加载 JSON 文件"""
    if default is None:
        default = {}
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default
    except Exception:
        return default


def save_json(filepath: str, data: Any) -> bool:
    """保存 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_http_client(timeout: int = 30) -> httpx.AsyncClient:
    """创建 HTTP 客户端"""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers={
            "User-Agent": "Yuuki-Bot/2.5.0",
            "Accept": "application/json",
        },
    )


async def download_file(url: str, filepath: str, timeout: int = 60) -> bool:
    """下载文件"""
    try:
        async with get_http_client(timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            return True
    except Exception:
        return False


def format_time(seconds: float) -> str:
    """格式化时间（秒转时分秒）"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}小时{minutes}分{secs}秒"
    elif minutes > 0:
        return f"{minutes}分{secs}秒"
    else:
        return f"{secs}秒"


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def remove_empty_lines(text: str) -> str:
    """移除空行"""
    lines = text.split("\n")
    return "\n".join(line for line in lines if line.strip())


def generate_random_string(length: int = 16) -> str:
    """生成随机字符串"""
    import random
    import string
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def get_file_size(filepath: str) -> int:
    """获取文件大小（字节）"""
    try:
        return os.path.getsize(filepath)
    except FileNotFoundError:
        return 0


def format_file_size(bytes_size: int) -> str:
    """格式化文件大小"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.2f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def delete_file(filepath: str):
    """删除文件"""
    try:
        os.remove(filepath)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def is_windows() -> bool:
    """检查是否为 Windows 系统"""
    return os.name == "nt"


def is_linux() -> bool:
    """检查是否为 Linux 系统"""
    return os.name == "posix" and os.uname().sysname == "Linux"


def is_macos() -> bool:
    """检查是否为 macOS 系统"""
    return os.name == "posix" and os.uname().sysname == "Darwin"


def get_system_info() -> Dict[str, str]:
    """获取系统信息"""
    return {
        "os": os.name,
        "platform": os.uname().sysname if hasattr(os, "uname") else "unknown",
        "python_version": os.sys.version.split()[0],
    }


async def run_with_retry(coro, max_retries: int = 3, delay: float = 2.0):
    """带重试的异步执行"""
    for attempt in range(max_retries):
        try:
            return await coro
        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
            else:
                raise


def merge_dicts(*dicts: Dict) -> Dict:
    """合并多个字典"""
    result = {}
    for d in dicts:
        result.update(d)
    return result


def get_common_prefix(strings: List[str]) -> str:
    """获取字符串列表的公共前缀"""
    if not strings:
        return ""
    
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
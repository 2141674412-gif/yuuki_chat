# ========== 自动更新 ==========

# 标准库
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime

# 第三方库
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException

# 从子模块导入
from .commands_base import _register, check_superuser, _get_http_client, _save_json, _load_json, _DATA_DIR, superusers

# GitHub 仓库配置
_GITHUB_REPO = "2141674412-gif/yuuki_chat"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_GITHUB_DOWNLOAD_URL = f"https://github.com/{_GITHUB_REPO}/releases/latest/download/yuuki_chat.zip"

# 更新配置
_UPDATE_DIR = os.path.join(_DATA_DIR, "update")  # 存放更新文件和元数据
_UPDATE_LOCK = os.path.join(_UPDATE_DIR, "updating.lock")  # 更新锁文件
_UPDATE_META = os.path.join(_UPDATE_DIR, "update.json")  # 版本元数据
_UPDATE_URL_FILE = os.path.join(_UPDATE_DIR, "update_url.txt")  # 下载地址配置
os.makedirs(_UPDATE_DIR, exist_ok=True)

# 默认更新下载地址（本地文件服务器）
_UPDATE_SERVER_DIR = os.path.join(os.getcwd(), "update_packages")
os.makedirs(_UPDATE_SERVER_DIR, exist_ok=True)


def _get_update_url() -> str:
    """获取更新下载地址"""
    if os.path.exists(_UPDATE_URL_FILE):
        try:
            with open(_UPDATE_URL_FILE, "r", encoding="utf-8") as f:
                url = f.read().strip()
            if url:
                return url
        except Exception:
            pass
    # 默认：GitHub Releases
    return _GITHUB_DOWNLOAD_URL


def _set_update_url(url: str):
    """设置更新下载地址"""
    try:
        with open(_UPDATE_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url.strip())
    except OSError as e:
        logger.error(f"[更新] 保存下载地址失败: {e}")


def _get_plugin_dir() -> str:
    """获取插件目录的绝对路径"""
    return os.path.dirname(os.path.abspath(__file__))


def _get_current_version() -> str:
    """获取当前版本（从 git hash 或文件时间戳）"""
    plugin_dir = _get_plugin_dir()
    # 优先从 .version 文件读取
    version_file = os.path.join(plugin_dir, ".version")
    if os.path.exists(version_file):
        try:
            with open(version_file, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    # 兜底：用文件修改时间
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _calc_file_hash(filepath: str) -> str:
    """计算文件的 SHA256 哈希"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


async def _cmd_update(event: MessageEvent):
    """自动更新插件（自动从远程下载）"""
    user_id = str(event.user_id)

    # 检查是否已经在更新中（锁文件超过5分钟视为过期，自动清理）
    if os.path.exists(_UPDATE_LOCK):
        try:
            lock_age = time.time() - os.path.getmtime(_UPDATE_LOCK)
            if lock_age > 300:  # 5分钟超时
                os.remove(_UPDATE_LOCK)
                logger.info("[更新] 锁文件已过期，自动清理")
            else:
                await _cmd_update_cmd.finish("...正在更新中，请稍等。")
                return
        except Exception:
            await _cmd_update_cmd.finish("...正在更新中，请稍等。")
            return

    update_zip = os.path.join(_UPDATE_DIR, "yuuki_chat.zip")

    # 尝试从远程下载更新包
    url = _get_update_url()
    await _cmd_update_cmd.send(f"...正在从远程下载更新包...")

    # 获取 GitHub 最新 Release tag 和 SHA256 digest
    remote_tag = None
    remote_digest = None
    try:
        client = _get_http_client()
        api_resp = await client.get(_GITHUB_API, timeout=10.0, headers={"Accept": "application/vnd.github.v3+json"})
        if api_resp.status_code == 200:
            data = api_resp.json()
            remote_tag = data.get("tag_name", None)
            # 获取 yuuki_chat.zip 的 sha256 digest
            for asset in data.get("assets", []):
                if asset.get("name") == "yuuki_chat.zip":
                    digest_val = asset.get("digest", "")
                    # digest 格式可能是 {"sha256": "abc..."} 或直接是字符串
                    if isinstance(digest_val, dict):
                        remote_digest = digest_val.get("sha256", "")
                    elif isinstance(digest_val, str):
                        # GitHub 格式: "sha256:abc123..." → "abc123"
                        if digest_val.startswith("sha256:"):
                            remote_digest = digest_val[7:]
                        else:
                            remote_digest = digest_val
                    break
    except Exception:
        pass

    try:
        client = _get_http_client()
        # 加随机参数绕过CDN缓存
        download_url = url
        if "github.com" in url and "?" not in url:
            download_url = f"{url}?t={int(time.time())}"
        resp = await client.get(download_url, timeout=30.0)
        if resp.status_code == 200:
            content = resp.content
            if len(content) < 1000:
                await _cmd_update_cmd.finish(f"...下载的文件太小（{len(content)}B），可能不是有效的更新包。")
                return
            with open(update_zip, "wb") as f:
                f.write(content)

            # 验证 SHA256 签名（如果远程版本和本地不同则跳过，因为CDN缓存可能导致不匹配）
            if remote_digest:
                sha256 = hashlib.sha256(content).hexdigest()
                old_version_tmp = ""
                if os.path.exists(_UPDATE_META):
                    try:
                        with open(_UPDATE_META, "r") as f:
                            old_version_tmp = json.load(f).get("version", "")
                    except Exception:
                        pass
                if remote_tag and old_version_tmp and remote_tag != old_version_tmp:
                    logger.warning(f"[更新] 远程版本 {remote_tag} != 本地版本 {old_version_tmp}，跳过签名验证（CDN缓存）")
                elif sha256 != remote_digest:
                    await _cmd_update_cmd.send("...签名验证失败！文件可能被篡改。拒绝更新。")
                    os.remove(update_zip)
                    return

            await _cmd_update_cmd.send(f"...下载完成（{len(content)/1024:.1f}KB），开始更新...")
        else:
            # 下载失败，检查本地是否有文件
            if os.path.exists(update_zip):
                await _cmd_update_cmd.send(f"...远程下载失败（HTTP {resp.status_code}），使用本地缓存文件...")
            else:
                await _cmd_update_cmd.finish(f"...下载失败（HTTP {resp.status_code}），本地也没有缓存文件。")
                return
    except Exception as e:
        if os.path.exists(update_zip):
            await _cmd_update_cmd.send(f"...远程下载失败（{type(e).__name__}），使用本地缓存文件...")
        else:
            await _cmd_update_cmd.finish(f"...下载失败：{type(e).__name__}: {e}")
            return

    # 检查更新文件是否存在
    if not os.path.exists(update_zip):
        await _cmd_update_cmd.finish("...没有找到更新文件。")
        return

    # 计算新文件哈希，和上次比较（但如果远程版本不同则强制更新）
    new_hash = _calc_file_hash(update_zip)
    old_hash = ""
    if os.path.exists(_UPDATE_META):
        try:
            with open(_UPDATE_META, "r") as f:
                meta = json.load(f)
                old_hash = meta.get("last_hash", "")
                old_version = meta.get("version", "")
        except Exception:
            pass

    # 如果远程版本和本地不同，跳过 hash 检查
    force_update = False
    if remote_tag and old_version and remote_tag != old_version:
        force_update = True
        logger.info(f"[更新] 远程版本 {remote_tag} != 本地版本 {old_version}，强制更新")

    if not force_update and new_hash == old_hash:
        await _cmd_update_cmd.finish("...已经是最新版本了，没有变化。")
        return

    # 创建锁文件
    try:
        with open(_UPDATE_LOCK, "w") as f:
            f.write(f"{user_id}\n{time.time()}")
    except Exception as e:
        await _cmd_update_cmd.finish(f"...创建更新锁失败：{e}")
        return

    try:
        # 验证 zip 文件
        await _cmd_update_cmd.send("...正在验证更新文件...")
        try:
            with zipfile.ZipFile(update_zip, "r") as zf:
                # 检查必要文件
                names = zf.namelist()
                required = ["__init__.py", "config.py", "chat.py", "commands_base.py"]
                missing = [f for f in required if f not in names]
                if missing:
                    await _cmd_update_cmd.finish(f"...更新文件不完整，缺少：{', '.join(missing)}")
                    return
                # 检查是否有危险路径（防止路径穿越）
                for name in names:
                    if name.startswith("/") or ".." in name:
                        await _cmd_update_cmd.finish("...更新文件包含非法路径，已取消。")
                        return
        except zipfile.BadZipFile:
            await _cmd_update_cmd.finish("...更新文件损坏（不是有效的 zip），请重新上传。")
            return

        # 备份当前版本
        plugin_dir = _get_plugin_dir()
        backup_dir = os.path.join(_UPDATE_DIR, "backup")
        os.makedirs(backup_dir, exist_ok=True)
        await _cmd_update_cmd.send("...正在备份当前版本...")

        # 只备份 .py 文件
        _PY_FILES = [
            "__init__.py", "config.py", "chat.py", "maimai.py", "utils.py",
            "commands_base.py", "commands_fun.py", "commands_checkin.py",
            "commands_remind.py", "commands_calc.py", "commands_translate.py",
            "commands_search.py", "commands_weather.py", "commands_wordcloud.py",
            "commands_admin.py", "commands_group_admin.py", "commands_update.py",
            "commands_schedule.py", "commands_backup.py", "commands_vault.py",
        ]
        backup_ok = True
        for fname in _PY_FILES:
            src = os.path.join(plugin_dir, fname)
            dst = os.path.join(backup_dir, fname)
            if os.path.exists(src):
                try:
                    with open(src, "rb") as sf, open(dst, "wb") as df:
                        df.write(sf.read())
                except Exception:
                    backup_ok = False

        if not backup_ok:
            await _cmd_update_cmd.send("...备份部分文件失败，但继续更新。")

        # 解压新文件（只覆盖 .py 文件，保留 assets 和 data）
        await _cmd_update_cmd.send("...正在更新文件...")
        extract_count = 0
        try:
            with zipfile.ZipFile(update_zip, "r") as zf:
                for name in zf.namelist():
                    # 跳过目录条目和隐藏文件
                    if name.endswith("/") or name.endswith("\\") or os.path.basename(name).startswith("."):
                        continue
                    # 只提取 .py 文件和 assets 目录下的文件
                    if name.endswith(".py") or name.startswith("assets/"):
                        # 安全路径拼接
                        target = os.path.join(plugin_dir, os.path.basename(name) if name.endswith(".py") else name)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        extract_count += 1

            # 清理旧文件（v2.0 重构后 commands.py 已拆分）
            old_files = ["commands.py"]
            for old in old_files:
                old_path = os.path.join(plugin_dir, old)
                if os.path.exists(old_path):
                    os.remove(old_path)
                    extract_count += 1
        except Exception as e:
            # 更新失败，尝试恢复备份
            await _cmd_update_cmd.send(f"...更新失败：{e}，正在恢复备份...")
            for fname in _PY_FILES:
                backup_file = os.path.join(backup_dir, fname)
                plugin_file = os.path.join(plugin_dir, fname)
                if os.path.exists(backup_file):
                    try:
                        with open(backup_file, "rb") as sf, open(plugin_file, "wb") as df:
                            df.write(sf.read())
                    except Exception:
                        pass
            await _cmd_update_cmd.finish("...更新失败，已恢复旧版本。")
            return

        # 更新元数据
        version = remote_tag or _get_current_version()
        try:
            with open(_UPDATE_META, "w") as f:
                json.dump({
                    "last_hash": new_hash,
                    "version": version,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "files": extract_count,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 删除更新文件和锁
        try:
            os.remove(update_zip)
        except Exception:
            pass
        try:
            os.remove(_UPDATE_LOCK)
        except Exception:
            pass

        await _cmd_update_cmd.send(f"...更新完成！已更新 {extract_count} 个文件。正在重启...")

        # 写入更新日志
        _append_changelog(version, f"自动更新，{extract_count} 个文件", user_id)

        # 自动重启
        project_dir = os.path.normpath(os.path.join(plugin_dir, '..', '..'))
        restart_file = os.path.join(project_dir, 'restart_flag.txt')
        restart_data = {'user_id': user_id, 'reason': '自动更新'}
        if hasattr(event, 'group_id') and event.group_id:
            restart_data['group_id'] = str(event.group_id)
        try:
            with open(restart_file, 'w', encoding='utf-8') as f:
                json.dump(restart_data, f)
        except Exception:
            pass

        try:
            bot_path = os.path.join(project_dir, 'bot.py')
            subprocess.Popen([sys.executable, bot_path], cwd=project_dir)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
        except Exception as e:
            await _cmd_update_cmd.finish(f"...更新成功但重启失败：{e}，请手动重启。")

    except FinishedException:
        raise
    except Exception as e:
        # 清理锁
        try:
            os.remove(_UPDATE_LOCK)
        except Exception:
            pass
        await _cmd_update_cmd.finish(f"...更新过程出错：{type(e).__name__}: {e}")


async def _cmd_update_status(event: MessageEvent):
    """查看更新状态"""
    lines = [f"当前版本：{_get_current_version()}"]
    lines.append(f"更新源：{_get_update_url()}")

    # 从 GitHub 检查最新 Release
    try:
        client = _get_http_client()
        resp = await client.get(_GITHUB_API, timeout=10.0, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code == 200:
            data = resp.json()
            latest_tag = data.get("tag_name", "未知")
            latest_name = data.get("name", "")
            latest_body = (data.get("body", "") or "").strip()
            published = data.get("published_at", "")[:16].replace("T", " ")
            lines.append(f"最新版本：{latest_tag}（{published}）")
            if latest_name:
                lines.append(f"标题：{latest_name}")
            # 显示更新日志前3行
            if latest_body:
                for line in latest_body.split("\n")[:5]:
                    line = line.strip()
                    if line:
                        lines.append(f"  {line}")
            # 检查本地版本是否和远程一致
            if os.path.exists(_UPDATE_META):
                try:
                    with open(_UPDATE_META, "r") as f:
                        meta = json.load(f)
                    if meta.get("version") == latest_tag:
                        lines.append("状态：已是最新版本")
                    else:
                        lines.append("状态：有新版本，发送 /更新 自动下载并更新")
                except Exception:
                    lines.append("状态：有新版本，发送 /更新 自动下载并更新")
            else:
                lines.append("状态：有新版本，发送 /更新 自动下载并更新")
        elif resp.status_code == 404:
            lines.append("远程：暂无 Release（请先在 GitHub 上传 Release）")
        else:
            lines.append(f"远程：查询失败（HTTP {resp.status_code}）")
    except Exception as e:
        lines.append(f"远程：查询失败（{type(e).__name__}）")

    # 检查本地缓存
    update_zip = os.path.join(_UPDATE_DIR, "yuuki_chat.zip")
    if os.path.exists(update_zip):
        new_hash = _calc_file_hash(update_zip)
        size_kb = os.path.getsize(update_zip) / 1024
        lines.append(f"本地缓存：yuuki_chat.zip ({size_kb:.1f}KB, hash={new_hash})")

    await _cmd_update_status_cmd.finish("\n".join(lines))


_cmd_update_cmd = _register("更新", _cmd_update, priority=1, admin_only=True)
_cmd_update_status_cmd = _register("更新状态", _cmd_update_status, priority=1, admin_only=True)


# ========== 更新下载地址管理 ==========

async def _cmd_set_update_url(event: MessageEvent):
    """设置更新下载地址"""
    content = str(event.message).strip()
    for prefix in ["设置更新地址", "seturl"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        url = _get_update_url()
        await _cmd_set_update_url_cmd.finish(f"...当前更新地址：{url}\n用法：/设置更新地址 URL")
        return

    _set_update_url(content)
    await _cmd_set_update_url_cmd.finish(f"...已设置更新地址：{content}")


async def _cmd_start_file_server(event: MessageEvent):
    """启动本地文件服务器（用于更新）"""
    port = 9999
    server_dir = _UPDATE_SERVER_DIR

    # 检查是否已在运行
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        if result == 0:
            await _cmd_start_file_server_cmd.finish(f"...文件服务器已在运行：http://127.0.0.1:{port}\n把 yuuki_chat.zip 放到 {server_dir} 目录下即可。")
            return
    except Exception:
        pass

    # 启动文件服务器（后台线程）
    import threading
    import http.server

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=server_dir, **kwargs)
        def log_message(self, format, *args):
            logger.debug(f"[文件服务器] {args[0]}")

    def _run_server():
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), _QuietHandler)
            logger.info(f"[文件服务器] 已启动 http://127.0.0.1:{port} 目录: {server_dir}")
            server.serve_forever()
        except Exception as e:
            logger.warning(f"[文件服务器] 启动失败: {e}")

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    # 设置更新地址
    _set_update_url(f"http://127.0.0.1:{port}/yuuki_chat.zip")

    await _cmd_start_file_server_cmd.send(
        f"...文件服务器已启动：http://127.0.0.1:{port}\n"
        f"目录：{server_dir}\n"
        f"把 yuuki_chat.zip 放到该目录下，然后发送 /更新 即可自动下载并更新。"
    )


_cmd_set_update_url_cmd = _register("设置更新地址", _cmd_set_update_url, admin_only=True)
_cmd_start_file_server_cmd = _register("启动文件服务", _cmd_start_file_server, admin_only=True)


# ========== 更新日志 ==========

_CHANGELOG_FILE = os.path.join(_DATA_DIR, "changelog.json")
_CHANGELOG = []  # [{"version": str, "content": str, "author": str, "time": str}, ...]

def _load_changelog():
    """加载更新日志"""
    global _CHANGELOG
    if os.path.exists(_CHANGELOG_FILE):
        try:
            with open(_CHANGELOG_FILE, "r", encoding="utf-8") as f:
                _CHANGELOG = json.load(f)
        except Exception:
            _CHANGELOG = []

def _save_changelog():
    """保存更新日志"""
    try:
        with open(_CHANGELOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_CHANGELOG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[更新日志] 保存失败: {e}")

def _append_changelog(version: str, content: str, author: str = "system"):
    """追加一条更新日志"""
    global _CHANGELOG
    _load_changelog()
    _CHANGELOG.append({
        "version": version,
        "content": content,
        "author": author,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    # 最多保留 50 条
    if len(_CHANGELOG) > 50:
        _CHANGELOG = _CHANGELOG[-50:]
    _save_changelog()

# 启动时加载
_load_changelog()

async def _cmd_changelog(event: MessageEvent):
    """查看更新日志（默认最近5条，支持分页）"""
    _load_changelog()
    if not _CHANGELOG:
        await _cmd_changelog_cmd.finish("...还没有更新记录。")
        return

    msg = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["更新日志", "changelog"]:
        if msg.lower().startswith(prefix.lower()):
            msg = msg[len(prefix):].strip()
            break

    total = _len_changelog()
    per_page = 5
    page = 1
    if msg.isdigit() and int(msg) >= 1:
        page = int(msg)
    max_page = (total + per_page - 1) // per_page
    if page > max_page:
        page = max_page

    start = total - page * per_page
    end = total - (page - 1) * per_page
    if start < 0:
        start = 0

    entries = _CHANGELOG[start:end]
    lines = [f"【更新日志】共 {total} 代（第{page}/{max_page}页）"]
    for i, entry in enumerate(reversed(entries), 1):
        idx = end - i + 1
        ver = entry.get("version", "?")
        content = entry.get("content", "")
        t = entry.get("time", "")
        lines.append(f"第{idx}代 | {ver} | {t} | {content}")

    if max_page > 1:
        lines.append(f"查看更多：/更新日志 {page + 1}" if page < max_page else f"已是最后一页，查看之前：/更新日志 {page - 1}")

    await _cmd_changelog_cmd.finish("\n".join(lines))

def _len_changelog() -> int:
    return len(_CHANGELOG)

async def _cmd_add_changelog(event: MessageEvent):
    """手动添加更新日志（管理员）"""
    content = str(event.message).strip()
    # 去掉命令前缀
    for prefix in ["记录更新", "addlog"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _cmd_add_changelog_cmd.finish("...记什么？用法：/记录更新 内容")
        return

    user_id = str(event.user_id)
    _append_changelog(f"v{_get_current_version()}", content, user_id)
    await _cmd_add_changelog_cmd.finish(f"...已记录。当前第 {_len_changelog()} 代。")

_cmd_changelog_cmd = _register("更新日志", _cmd_changelog, aliases=["changelog"])
_cmd_add_changelog_cmd = _register("记录更新", _cmd_add_changelog, aliases=["addlog"], admin_only=True)

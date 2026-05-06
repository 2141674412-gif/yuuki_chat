# ========== 自动更新 ==========

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from io import BytesIO

import nonebot
from nonebot import logger, get_bot, Driver
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.exception import FinishedException

from .commands_base import _register, check_superuser, check_owner, _get_http_client, _save_json, _load_json, _DATA_DIR, superusers, send_msg as _send


_GITHUB_REPO = "2141674412-gif/yuuki_chat"
_GITHUB_API = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_GITHUB_DOWNLOAD_URL = f"https://github.com/{_GITHUB_REPO}/releases/latest/download/yuuki_chat.zip"

_UPDATE_DIR = os.path.join(_DATA_DIR, "update")
_UPDATE_LOCK = os.path.join(_UPDATE_DIR, "updating.lock")
_UPDATE_META = os.path.join(_UPDATE_DIR, "update.json")
_UPDATE_URL_FILE = os.path.join(_UPDATE_DIR, "update_url.txt")
os.makedirs(_UPDATE_DIR, exist_ok=True)

_UPDATE_SERVER_DIR = os.path.join(os.getcwd(), "update_packages")
os.makedirs(_UPDATE_SERVER_DIR, exist_ok=True)

_PY_FILES = [
    "__init__.py", "config.py", "chat.py", "maimai.py", "utils.py",
    "commands_base.py", "commands_fun.py", "commands_checkin.py",
    "commands_remind.py", "commands_calc.py", "commands_translate.py",
    "commands_search.py", "commands_weather.py", "commands_wordcloud.py",
    "commands_admin.py", "commands_group_admin.py", "commands_update.py",
    "commands_schedule.py", "commands_backup.py", "commands_vault.py",
    "commands_sticker.py", "commands_remote.py", "commands_diagnose.py",
    "commands_birthday.py", "commands_dongle.py", "commands_mqtt.py",
    "commands_wzry.py", "commands_accounting.py",
]

_MAX_RETRIES = 3
_RETRY_DELAY = 2
_DOWNLOAD_TIMEOUT = 90
_LOCK_TIMEOUT = 300

_UPDATE_CHECK_INTERVAL = 3600
_last_update_check = 0


def _get_plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _get_current_version() -> str:
    plugin_dir = _get_plugin_dir()
    version_file = os.path.join(plugin_dir, ".version")
    if os.path.exists(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    if os.path.exists(_UPDATE_META):
        try:
            with open(_UPDATE_META, "r", encoding="utf-8") as f:
                data = json.load(f)
                v = data.get("version", "")
                if v:
                    return v
        except Exception:
            pass
    return "未知"


def _get_update_url() -> str:
    if os.path.exists(_UPDATE_URL_FILE):
        try:
            with open(_UPDATE_URL_FILE, "r", encoding="utf-8") as f:
                url = f.read().strip()
            if url and url.startswith(("http://", "https://")):
                return url
        except Exception:
            pass
    return _GITHUB_DOWNLOAD_URL


def _set_update_url(url: str):
    try:
        with open(_UPDATE_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url.strip())
    except OSError as e:
        logger.error(f"[更新] 保存下载地址失败: {e}")


def _save_version(version: str):
    try:
        version_file = os.path.join(_get_plugin_dir(), ".version")
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(version)
    except Exception:
        pass
    try:
        with open(_UPDATE_META, "w", encoding="utf-8") as f:
            json.dump({
                "version": version,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


async def _fetch_remote_info(client):
    remote_tag = None
    remote_digest = None
    release_body = None
    try:
        resp = await client.get(
            _GITHUB_API,
            timeout=15.0,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "yuuki-bot-updater"}
        )
        if resp.status_code == 200:
            data = resp.json()
            remote_tag = data.get("tag_name")
            release_body = data.get("body", "")
            for asset in data.get("assets", []):
                if asset.get("name") == "yuuki_chat.zip":
                    digest_val = asset.get("digest", "")
                    if isinstance(digest_val, dict):
                        remote_digest = digest_val.get("sha256", "")
                    elif isinstance(digest_val, str) and digest_val.startswith("sha256:"):
                        remote_digest = digest_val[7:]
                    break
            return remote_tag, remote_digest, release_body
    except Exception as e:
        logger.warning(f"[更新] 获取远程信息失败: {e}")
    return remote_tag, remote_digest, release_body


async def _download_update(client, url, retry_count=0):
    update_zip = os.path.join(_UPDATE_DIR, "yuuki_chat.zip")
    download_url = url
    if "github.com" in url and "?" not in url:
        download_url = f"{url}?t={int(time.time())}"

    try:
        resp = await client.get(download_url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
        if resp.status_code != 200:
            if retry_count < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY)
                return await _download_update(client, url, retry_count + 1)
            return False, f"HTTP {resp.status_code}"

        content = resp.content
        if len(content) < 1000:
            return False, f"文件太小（{len(content)}B）"

        with open(update_zip, "wb") as f:
            f.write(content)
        return True, update_zip

    except asyncio.TimeoutError:
        if retry_count < _MAX_RETRIES:
            logger.info(f"[更新] 下载超时，重试 {retry_count + 1}/{_MAX_RETRIES}")
            await asyncio.sleep(_RETRY_DELAY)
            return await _download_update(client, url, retry_count + 1)
        return False, "下载超时"
    except Exception as e:
        if retry_count < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)
            return await _download_update(client, url, retry_count + 1)
        return False, f"{type(e).__name__}: {e}"


def _verify_zip(filepath):
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            names = zf.namelist()
            required = ["__init__.py", "config.py", "chat.py", "commands_base.py"]
            missing = [f for f in required if f not in names]
            if missing:
                return False, f"缺少：{', '.join(missing)}"
            for name in names:
                if name.startswith("/") or ".." in name:
                    return False, "包含非法路径"
            bad_file = zf.testzip()
            if bad_file:
                return False, f"文件损坏：{bad_file}"
        return True, ""
    except zipfile.BadZipFile:
        return False, "文件损坏（不是有效的zip）"
    except Exception as e:
        return False, f"验证失败：{type(e).__name__}"


def _backup_current():
    plugin_dir = _get_plugin_dir()
    backup_dir = os.path.join(_UPDATE_DIR, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    backup_count = 0
    for fname in _PY_FILES:
        src = os.path.join(plugin_dir, fname)
        dst = os.path.join(backup_dir, fname)
        if os.path.exists(src):
            try:
                shutil.copy2(src, dst)
                backup_count += 1
            except Exception as e:
                logger.warning(f"[更新] 备份失败 {fname}: {e}")
    return backup_count


def _restore_backup():
    plugin_dir = _get_plugin_dir()
    backup_dir = os.path.join(_UPDATE_DIR, "backup")
    restore_count = 0
    for fname in _PY_FILES:
        backup_file = os.path.join(backup_dir, fname)
        plugin_file = os.path.join(plugin_dir, fname)
        if os.path.exists(backup_file):
            try:
                shutil.copy2(backup_file, plugin_file)
                restore_count += 1
            except Exception as e:
                logger.warning(f"[更新] 恢复失败 {fname}: {e}")
    return restore_count


async def _extract_update(filepath):
    import tempfile
    plugin_dir = _get_plugin_dir()
    plugin_dir_real = os.path.realpath(plugin_dir)
    file_list = []

    tmp_dir = tempfile.mkdtemp(prefix="yuuki_update_")

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/") or name.endswith("\\") or os.path.basename(name).startswith("."):
                    continue
                if not (name.endswith(".py") or name.endswith(".json") or name.startswith("assets/")):
                    continue

                if name.endswith(".py"):
                    target = os.path.join(plugin_dir, os.path.basename(name))
                else:
                    target = os.path.join(plugin_dir, name)

                target_real = os.path.realpath(os.path.dirname(target))
                try:
                    target_real = os.path.realpath(target)
                except Exception:
                    pass

                if not target_real.startswith(plugin_dir_real + os.sep) and target_real != plugin_dir_real:
                    logger.warning(f"[更新] 跳过非法路径: {name}")
                    continue

                tmp_target = os.path.join(tmp_dir, os.path.basename(name) if name.endswith(".py") else name)
                os.makedirs(os.path.dirname(tmp_target), exist_ok=True)
                with zf.open(name) as src, open(tmp_target, "wb") as dst:
                    dst.write(src.read())
                file_list.append((name, target))

    except zipfile.BadZipFile as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ValueError(f"ZIP文件损坏: {e}")

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-q", "--upgrade-strategy", "only-if-needed", "nonebot-plugin-parser",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        logger.info("[更新] 已安装 nonebot-plugin-parser")
    except asyncio.TimeoutError:
        logger.warning("[更新] 安装依赖超时")
    except Exception as e:
        logger.warning(f"[更新] 安装依赖失败: {e}")

    return file_list, tmp_dir


def _apply_update(file_list, tmp_dir):
    extract_count = 0

    for name, target in file_list:
        tmp_target = os.path.join(tmp_dir, os.path.basename(name) if name.endswith(".py") else name)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(tmp_target, target)
            extract_count += 1
        except Exception as e:
            logger.warning(f"[更新] 复制失败 {name}: {e}")

    plugin_dir = _get_plugin_dir()
    for old in ["commands.py", "commands_bilibili.py", "onebot_client.py"]:
        old_path = os.path.join(plugin_dir, old)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    return extract_count


def _do_restart(user_id, event, reason="手动重启"):
    import time as time_module
    plugin_dir = _get_plugin_dir()
    project_dir = os.path.normpath(os.path.join(plugin_dir, '..', '..'))
    restart_file = os.path.join(project_dir, 'restart_flag.json')
    restart_data = {
        'user_id': user_id,
        'reason': reason,
        'timestamp': str(int(time_module.time()))
    }
    if hasattr(event, 'group_id') and event.group_id:
        restart_data['group_id'] = str(event.group_id)
    try:
        with open(restart_file, 'w', encoding='utf-8') as f:
            json.dump(restart_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        import sentry_sdk
        sentry_sdk.flush()
    except Exception:
        pass

    try:
        bot_path = os.path.join(project_dir, 'bot.py')
        if sys.platform == "win32":
            subprocess.Popen(
                [sys.executable, bot_path],
                cwd=project_dir,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            subprocess.Popen(
                [sys.executable, bot_path],
                cwd=project_dir,
                start_new_session=True
            )
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    except Exception as e:
        return str(e)
    return None


def _cleanup_old_files():
    try:
        for fname in os.listdir(_UPDATE_DIR):
            fpath = os.path.join(_UPDATE_DIR, fname)
            if fname.endswith(".zip") and fname != "yuuki_chat.zip":
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        tmp_dirs = [d for d in os.listdir(_UPDATE_DIR) if d.startswith("yuuki_update_")]
        for d in tmp_dirs:
            try:
                shutil.rmtree(os.path.join(_UPDATE_DIR, d), ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def _notify_superusers(bot: Bot, message: str):
    for uid in superusers:
        try:
            asyncio.create_task(bot.send_private_msg(user_id=int(uid), message=Message(message)))
        except Exception as e:
            logger.warning(f"[更新] 通知 superuser {uid} 失败: {e}")


async def _check_update_notify():
    global _last_update_check
    try:
        if time.time() - _last_update_check < _UPDATE_CHECK_INTERVAL:
            return
        _last_update_check = time.time()

        client = _get_http_client()
        remote_tag, remote_digest, release_body = await _fetch_remote_info(client)
        if not remote_tag:
            return

        current_version = _get_current_version()
        if remote_tag != current_version:
            try:
                bot = get_bot()
                notify_msg = (
                    f"🌟 发现新版本！\n"
                    f"当前版本：{current_version}\n"
                    f"最新版本：{remote_tag}\n"
                    f"发送 /更新 来更新哦~"
                )
                _notify_superusers(bot, notify_msg)
                logger.info(f"[更新] 发现新版本 {remote_tag}，已通知 superusers")
            except Exception as e:
                logger.warning(f"[更新] 通知失败: {e}")
    except Exception as e:
        logger.warning(f"[更新] 检查更新失败: {e}")


async def _cmd_update(event: MessageEvent):
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能更新。")
        return
    user_id = str(event.user_id)
    logger.info(f"[更新] 收到更新请求 from {user_id}")

    try:
        bot: Bot = get_bot()
    except Exception:
        logger.error("[更新] 无法获取bot实例")
        return

    async def _send_progress(msg):
        try:
            if hasattr(event, 'group_id') and event.group_id:
                await bot.send_group_msg(group_id=event.group_id, message=Message(msg))
            else:
                await bot.send_private_msg(user_id=_safe_int(user_id), message=Message(msg))
        except FinishedException:
            raise
        except Exception as e:
            logger.error(f"[更新] 发送消息失败: {e}")

    if os.path.exists(_UPDATE_LOCK):
        try:
            lock_age = time.time() - os.path.getmtime(_UPDATE_LOCK)
            if lock_age > _LOCK_TIMEOUT:
                os.remove(_UPDATE_LOCK)
            else:
                await _send_progress("...正在更新中，请稍等。")
                return
        except Exception:
            await _send_progress("...正在更新中，请稍等。")
            return

    _cleanup_old_files()

    await _send_progress("...正在检查更新...")
    client = _get_http_client()
    remote_tag, remote_digest, release_body = await _fetch_remote_info(client)

    if not remote_tag:
        await _send_progress("...无法获取远程版本信息，请稍后再试。")
        return

    current_version = _get_current_version()
    if remote_tag == current_version:
        await _send_progress("...已经是最新版本了。")
        return

    await asyncio.sleep(1)
    await _send_progress(f"...发现新版本 {remote_tag}，正在下载...")
    url = _get_update_url()
    ok, result = await _download_update(client, url)

    if not ok:
        await _send_progress(f"...下载失败：{result}")
        return

    update_zip = result
    size_kb = os.path.getsize(update_zip) / 1024

    if remote_digest:
        try:
            with open(update_zip, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            if sha256 != remote_digest:
                await _send_progress("...签名验证失败！文件可能被篡改。")
                try:
                    os.remove(update_zip)
                except Exception:
                    pass
                return
        except Exception as e:
            logger.warning(f"[更新] SHA256验证失败: {e}")

    await asyncio.sleep(1)
    await _send_progress(f"...下载完成（{size_kb:.1f}KB），正在验证...")

    ok, err = _verify_zip(update_zip)
    if not ok:
        await _send_progress(f"...更新文件无效：{err}")
        return

    try:
        with open(_UPDATE_LOCK, "w", encoding="utf-8") as f:
            f.write(f"{user_id}\n{time.time()}")
    except Exception:
        pass

    try:
        await asyncio.sleep(1)
        await _send_progress("...正在备份...")
        backup_count = _backup_current()
        logger.info(f"[更新] 已备份 {backup_count} 个文件")

        await asyncio.sleep(1)
        await _send_progress("...正在更新文件...")
        file_list, tmp_dir = await _extract_update(update_zip)
        extract_count = len(file_list)

        _save_version(remote_tag)
        try:
            pending_file = os.path.join(os.path.dirname(_get_plugin_dir()), "_pending_update.json")
            with open(pending_file, "w", encoding="utf-8") as f:
                json.dump({"tmp_dir": tmp_dir, "files": [(n, t) for n, t in file_list]}, f)
        except Exception:
            pass

        for f in [update_zip, _UPDATE_LOCK]:
            try:
                os.remove(f)
            except Exception:
                pass

        _append_changelog(remote_tag, f"自动更新，{extract_count} 个文件", user_id)

        await asyncio.sleep(1)
        await _send_progress(f"...更新完成！{remote_tag}，{extract_count} 个文件。正在重启...")

        err = _do_restart(user_id, event, reason="自动更新")
        if err:
            await _send_progress(f"...更新成功但重启失败：{err}，请手动重启。")

    except FinishedException:
        raise
    except Exception as e:
        _restore_backup()
        try:
            os.remove(_UPDATE_LOCK)
        except Exception:
            pass
        await _send_progress(f"...更新失败，已恢复旧版本：{type(e).__name__}")


async def _cmd_update_status(event: MessageEvent):
    lines = [f"当前版本：{_get_current_version()}"]
    lines.append(f"更新源：{_get_update_url()}")

    try:
        client = _get_http_client()
        resp = await client.get(
            _GITHUB_API,
            timeout=10.0,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "yuuki-bot-updater"}
        )
        if resp.status_code == 200:
            data = resp.json()
            latest_tag = data.get("tag_name", "未知")
            published = data.get("published_at", "")[:16].replace("T", " ")
            lines.append(f"最新版本：{latest_tag}（{published}）")

            current = _get_current_version()
            if current == latest_tag:
                lines.append("状态：已是最新版本")
            else:
                lines.append("状态：有新版本，发送 /更新")

            body = (data.get("body", "") or "").strip()
            if body:
                for line in body.split("\n")[:5]:
                    line = line.strip()
                    if line:
                        lines.append(f"  {line}")
        elif resp.status_code == 404:
            lines.append("远程：暂无 Release")
        else:
            lines.append(f"远程：查询失败（HTTP {resp.status_code}）")
    except Exception as e:
        lines.append(f"远程：查询失败（{type(e).__name__}）")

    await _send(event, "\n".join(lines))


_cmd_update_cmd = _register("更新", _cmd_update, priority=1, admin_only=True)
_cmd_update_status_cmd = _register("更新状态", _cmd_update_status, priority=1, admin_only=True)


async def _cmd_check_update(event: MessageEvent):
    user_id = str(event.user_id)
    try:
        bot: Bot = get_bot()
    except Exception:
        await _send(event, "...无法获取bot实例。")
        return

    await _send(event, "...正在检查更新...")

    client = _get_http_client()
    remote_tag, remote_digest, release_body = await _fetch_remote_info(client)

    if not remote_tag:
        await _send(event, "...无法获取远程版本信息，请稍后再试。")
        return

    current_version = _get_current_version()

    if remote_tag == current_version:
        await _send(event, f"...当前已是最新版本 {current_version}，没有可用更新。")
        return

    msg_parts = [
        f"🌟 发现新版本！",
        f"当前版本：{current_version}",
        f"最新版本：{remote_tag}",
        "",
    ]

    if release_body:
        body_lines = release_body.strip().split("\n")[:10]
        msg_parts.append("更新内容：")
        for line in body_lines:
            line = line.strip()
            if line:
                msg_parts.append(f"  {line}")

    msg_parts.append("")
    msg_parts.append("发送 /更新 来更新哦~")

    await _send(event, "\n".join(msg_parts))


_cmd_check_update_cmd = _register("检查更新", _cmd_check_update, aliases=["检查版本", "查版本", "版本", "ver", "version"], priority=1)


async def _cmd_set_update_url(event: MessageEvent):
    if not check_owner(str(event.user_id)):
        await _send(event, "...只有主人才能设置。")
        return
    content = str(event.message).strip()
    for prefix in ["设置更新地址", "seturl"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        url = _get_update_url()
        await _send(event, f"...当前更新地址：{url}\n用法：/设置更新地址 URL")
        return

    if not content.startswith(("http://", "https://")):
        await _send(event, "...URL格式不对，需要以 http:// 或 https:// 开头。")
        return

    _set_update_url(content)
    await _send(event, f"...已设置更新地址：{content}")


async def _cmd_start_file_server(event: MessageEvent):
    port = 9999
    server_dir = _UPDATE_SERVER_DIR

    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        if result == 0:
            await _send(event,
                f"...文件服务器已在运行：http://127.0.0.1:{port}\n"
                f"把 yuuki_chat.zip 放到 {server_dir} 目录下即可。")
            return
    except FinishedException:
        raise
    except Exception:
        pass

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
            logger.info(f"[文件服务器] 已启动 http://127.0.0.1:{port}")
            server.serve_forever()
        except Exception as e:
            logger.warning(f"[文件服务器] 启动失败: {e}")

    threading.Thread(target=_run_server, daemon=True).start()
    _set_update_url(f"http://127.0.0.1:{port}/yuuki_chat.zip")

    await _send(event,
        f"...文件服务器已启动：http://127.0.0.1:{port}\n"
        f"目录：{server_dir}\n"
        f"把 yuuki_chat.zip 放到该目录下，然后发送 /更新 即可。")


_cmd_set_update_url_cmd = _register("设置更新地址", _cmd_set_update_url, admin_only=True)
_cmd_start_file_server_cmd = _register("启动文件服务", _cmd_start_file_server, admin_only=True)


_CHANGELOG_FILE = os.path.join(_DATA_DIR, "changelog.json")
_CHANGELOG = []


def _load_changelog():
    global _CHANGELOG
    if os.path.exists(_CHANGELOG_FILE):
        try:
            with open(_CHANGELOG_FILE, "r", encoding="utf-8") as f:
                _CHANGELOG = json.load(f)
        except Exception:
            _CHANGELOG = []


def _save_changelog():
    try:
        with open(_CHANGELOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_CHANGELOG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[更新日志] 保存失败: {e}")


def _append_changelog(version: str, content: str, author: str = "system"):
    global _CHANGELOG
    _load_changelog()
    _CHANGELOG.append({
        "version": version,
        "content": content,
        "author": author,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    if len(_CHANGELOG) > 50:
        _CHANGELOG = _CHANGELOG[-50:]
    _save_changelog()


_load_changelog()


async def _cmd_changelog(event: MessageEvent):
    _load_changelog()
    if not _CHANGELOG:
        await _send(event, "...还没有更新记录。")
        return

    msg = str(event.message).strip()
    for prefix in ["更新日志", "changelog"]:
        if msg.lower().startswith(prefix.lower()):
            msg = msg[len(prefix):].strip()
            break

    total = len(_CHANGELOG)
    per_page = 5
    page = 1
    if msg.isdigit():
        page = max(1, _safe_int(msg))
    max_page = max(1, (total + per_page - 1) // per_page)
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
        if page < max_page:
            lines.append(f"查看更多：/更新日志 {page + 1}")
        else:
            lines.append(f"已是最后一页，查看之前：/更新日志 {page - 1}")

    await _send(event, "\n".join(lines))


async def _cmd_add_changelog(event: MessageEvent):
    content = str(event.message).strip()
    for prefix in ["记录更新", "addlog"]:
        if content.lower().startswith(prefix.lower()):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _send(event, "...记什么？用法：/记录更新 内容")
        return

    _append_changelog(f"v{_get_current_version()}", content, str(event.user_id))
    await _send(event, f"...已记录。当前第 {len(_CHANGELOG)} 代。")


_cmd_changelog_cmd = _register("更新日志", _cmd_changelog, aliases=["changelog"])
_cmd_add_changelog_cmd = _register("记录更新", _cmd_add_changelog, aliases=["addlog"], admin_only=True)


@nonebot.get_driver().on_startup
async def _on_startup_check_update():
    await asyncio.sleep(30)
    asyncio.create_task(_check_update_notify())


@nonebot.get_driver().on_bot_connect
async def _on_bot_connect(bot: Bot):
    asyncio.create_task(_check_update_notify())

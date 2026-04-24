# ========== 定时自动备份 ==========

# 标准库
import os
import shutil
import time
import zipfile
from datetime import datetime

# 第三方库
from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

# 从子模块导入
from .commands_base import _register, check_superuser, _DATA_DIR, superusers


BACKUP_DIR = os.path.join(_DATA_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

async def _do_backup(bot=None, group_id=None):
    """执行备份，返回备份文件路径或 None"""
    try:
        today = datetime.now().strftime("%Y%m%d")
        backup_file = os.path.join(BACKUP_DIR, f"backup_{today}.zip")
        # 如果今天已备份则跳过
        if os.path.exists(backup_file):
            logger.info(f"[备份] 今日备份已存在: {backup_file}")
            return backup_file
        # 收集数据文件
        data_files = []
        for fname in os.listdir(_DATA_DIR):
            fpath = os.path.join(_DATA_DIR, fname)
            if os.path.isfile(fpath):
                data_files.append(fpath)
        if not data_files:
            logger.warning("[备份] 没有数据文件可备份")
            return None
        with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in data_files:
                arcname = os.path.basename(fpath)
                zf.write(fpath, arcname)
        logger.info(f"[备份] 备份完成: {backup_file} ({os.path.getsize(backup_file)}B)")
        # 清理超过7天的备份
        _cleanup_old_backups()
        return backup_file
    except Exception as e:
        logger.error(f"[备份] 备份失败: {e}")
        return None

def _cleanup_old_backups():
    """清理超过7天的备份"""
    try:
        now = time.time()
        for fname in os.listdir(BACKUP_DIR):
            if not fname.startswith("backup_") or not fname.endswith(".zip"):
                continue
            fpath = os.path.join(BACKUP_DIR, fname)
            if now - os.path.getmtime(fpath) > 7 * 86400:
                os.remove(fpath)
                logger.info(f"[备份] 已清理旧备份: {fname}")
    except Exception as e:
        logger.error(f"[备份] 清理旧备份失败: {e}")

async def _cmd_manual_backup(event: MessageEvent):
    """手动备份：/手动备份"""
    if not check_superuser(str(event.user_id)):
        await manual_backup_cmd.finish("...你不是管理员。")
        return
    await manual_backup_cmd.send("正在备份中...")
    result = await _do_backup()
    if result:
        await manual_backup_cmd.finish(f"备份完成！文件：{os.path.basename(result)}")
    else:
        await manual_backup_cmd.finish("...备份失败了，看看日志吧。")

manual_backup_cmd = _register("手动备份", _cmd_manual_backup, admin_only=True)

# 每天凌晨3点自动备份
def _setup_auto_backup():
    try:
        from .commands_schedule import _get_scheduler
        _get_scheduler().add_job(
            _do_backup,
            "cron",
            hour=3,
            minute=0,
            id="daily_backup",
            replace_existing=True,
        )
        logger.info("[备份] 每日自动备份已注册（凌晨3:00）")
    except Exception as e:
        logger.error(f"[备份] 自动备份注册失败: {e}")

from nonebot import get_driver
_driver = get_driver()
@_driver.on_startup
async def _on_startup_backup():
    _setup_auto_backup()


# ========== 数据导出/导入 ==========

EXPORT_FILES = [
    "checkin_records.json", "user_points.json", "reminders.json",
    "maimai_binds.json", "allowed_groups.json", "user_blacklist.json",
    "vault.enc", "persona.txt", "scheduled_tasks.json",
]

async def _cmd_export(event: MessageEvent):
    """导出数据：/导出"""
    if not isinstance(event, GroupMessageEvent):
        await export_cmd.finish("...导出命令只能在群里用。")
        return
    if not check_superuser(str(event.user_id)):
        await export_cmd.finish("...你不是管理员。")
        return
    try:
        export_path = os.path.join(_DATA_DIR, "export_temp.zip")
        with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in EXPORT_FILES:
                fpath = os.path.join(_DATA_DIR, fname)
                if os.path.exists(fpath):
                    zf.write(fpath, fname)
        # 发送文件
        try:
            bot = get_bot()
            await bot.upload_group_file(
                group_id=event.group_id,
                file=export_path,
                name=f"yuuki_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            )
            await export_cmd.finish("数据已导出~")
        except Exception:
            # 如果群文件上传失败，尝试私聊发送
            await export_cmd.finish("...群文件上传失败，请尝试在私聊中使用。")
        finally:
            if os.path.exists(export_path):
                os.remove(export_path)
    except Exception as e:
        logger.error(f"[导出] 失败: {e}")
        await export_cmd.finish(f"...导出失败了：{e}")

async def _cmd_import(event: MessageEvent):
    """导入数据：/导入（需要上传zip文件）"""
    if not check_superuser(str(event.user_id)):
        await import_cmd.finish("...你不是管理员。")
        return
    # 检查是否有文件
    file_seg = None
    for seg in event.message:
        if seg.type == "file":
            file_seg = seg
            break
    if not file_seg:
        await import_cmd.finish("...请附上要导入的 zip 文件。用法：/导入 + 上传文件")
        return
    file_url = file_seg.data.get("url", "")
    file_name = file_seg.data.get("file", "") or file_seg.data.get("filename", "data.zip")
    if not file_url:
        await import_cmd.finish("...无法获取文件，请重试。")
        return
    await import_cmd.send(f"正在导入 {file_name}，这将覆盖现有数据...")
    try:
        from .utils import get_shared_http_client as _get_http_client
        client = _get_http_client()
        resp = await client.get(file_url, timeout=30.0)
        resp.raise_for_status()
        zip_data = resp.content
        # 解压到临时目录
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "import.zip")
            with open(zip_path, "wb") as f:
                f.write(zip_data)
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Zip Slip 防护：检查所有文件名
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name.split("/"):
                        await import_cmd.finish("...zip 文件包含非法路径，拒绝导入。")
                        return
                zf.extractall(tmpdir)
            # 复制文件
            imported = []
            for fname in EXPORT_FILES:
                src = os.path.join(tmpdir, fname)
                if os.path.exists(src):
                    dst = os.path.join(_DATA_DIR, fname)
                    shutil.copy2(src, dst)
                    imported.append(fname)
        if imported:
            # 重新加载数据
            from .commands_base import _load_checkin_records, _load_reminders, _load_points, _load_blacklist
            _load_checkin_records()
            _load_reminders()
            _load_points()
            _load_blacklist()
            from .commands_schedule import _load_scheduled_tasks
            _load_scheduled_tasks()
            await import_cmd.finish(f"导入完成！已导入 {len(imported)} 个文件：{', '.join(imported)}")
        else:
            await import_cmd.finish("...zip 中没有找到可导入的数据文件。")
    except Exception as e:
        logger.error(f"[导入] 失败: {e}")
        await import_cmd.finish(f"...导入失败了：{e}")

export_cmd = _register("导出", _cmd_export, admin_only=True)
import_cmd = _register("导入", _cmd_import, admin_only=True)

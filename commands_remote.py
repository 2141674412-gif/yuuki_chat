# ========== 远程执行（仅管理员） ==========

import os
import sys
import subprocess
import tempfile
import asyncio
import re
import shutil

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

# 从子模块导入
from .commands_base import _register, check_superuser

# 安全配置
# 允许执行的命令白名单（正则），空列表表示允许所有（仅限管理员）
_ALLOWED_CMD_PATTERNS = []
# 命令执行超时（秒）
_CMD_TIMEOUT = 30
# 最大输出长度（字符）
_MAX_OUTPUT = 3000
# 脚本执行超时（秒）
_SCRIPT_TIMEOUT = 60
# 最大脚本文件大小（字节）
_MAX_SCRIPT_SIZE = 100 * 1024  # 100KB
# 允许的脚本扩展名
_ALLOWED_SCRIPT_EXT = {'.py', '.sh', '.bat', '.ps1', '.js', '.lua', '.rb', '.go'}


def _is_cmd_allowed(cmd: str) -> bool:
    """检查命令是否在白名单中"""
    if not _ALLOWED_CMD_PATTERNS:
        return True  # 空白名单=允许所有（仅限管理员）
    return any(re.match(p, cmd) for p in _ALLOWED_CMD_PATTERNS)


async def _cmd_run(event: MessageEvent):
    """远程执行命令：/run <命令>"""
    if not check_superuser(str(event.user_id)):
        await run_cmd.finish("...你不是管理员。")
        return

    content = str(event.message).strip()
    for prefix in ["run", "执行"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await run_cmd.finish("...格式：/run <命令>\n示例：/run ls -la\n/run python -c \"print('hello')\"")
        return

    if not _is_cmd_allowed(content):
        await run_cmd.finish("...这个命令不在白名单里。")
        return

    await run_cmd.send(f"...执行中：`{content}`")

    try:
        # 使用shell=False防止shell注入，但需要手动解析命令
        # 对于简单命令直接用exec，管道等复杂命令仍用shell（管理员信任）
        if any(c in content for c in ('|', '&&', '||', '>', '<', '$(', '`')):
            # 包含shell特性的命令，使用shell（管理员已验证）
            proc = await asyncio.create_subprocess_shell(
                content,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )
        else:
            # 简单命令，用exec防止注入
            import shlex
            try:
                args = shlex.split(content, posix=(sys.platform != "win32"))
            except ValueError:
                args = content.split()
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.getcwd()
            )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CMD_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            await run_cmd.finish(f"...执行超时（{_CMD_TIMEOUT}秒），已终止。")
            return

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode

        result_parts = []
        if stdout_str:
            result_parts.append(stdout_str)
        if stderr_str:
            result_parts.append(f"[stderr]\n{stderr_str}")

        result = "\n".join(result_parts) if result_parts else "(无输出)"

        # 截断过长输出
        if len(result) > _MAX_OUTPUT:
            result = result[:_MAX_OUTPUT] + f"\n...（输出过长，已截断，共{len(result)}字符）"

        msg = f"退出码：{exit_code}\n{'━' * 20}\n{result}"
        await run_cmd.finish(msg)

    except Exception as e:
        await run_cmd.finish(f"...执行出错：{type(e).__name__}: {e}")


run_cmd = _register("run", _cmd_run, aliases=["执行"], priority=1, admin_only=True)


async def _cmd_exec(event: MessageEvent):
    """执行上传的脚本：发脚本文件给bot（需@），自动执行"""
    if not check_superuser(str(event.user_id)):
        await exec_cmd.finish("...你不是管理员。")
        return

    # 检查消息是否包含文件
    has_file = False
    file_data = None
    file_name = ""

    for seg in event.message:
        if seg.type == "file":
            has_file = True
            file_name = seg.data.get("name", "script")
            file_url = seg.data.get("url", "")
            if file_url:
                try:
                    from .utils import get_shared_http_client
                    resp = await get_shared_http_client().get(file_url, timeout=15.0)
                    if resp.status_code == 200:
                        file_data = resp.content
                except Exception:
                    pass
            # 有些实现直接在data里放file
            if not file_data:
                file_path = seg.data.get("file", "")
                if file_path and os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        file_data = f.read()
            break

    if not has_file or not file_data:
        await exec_cmd.finish("...请发送脚本文件给我执行。\n格式：@希亚 + 文件\n支持的格式：.py .sh .bat .js .lua .rb .go")
        return

    # 检查文件大小
    if len(file_data) > _MAX_SCRIPT_SIZE:
        await exec_cmd.finish(f"...文件太大（{len(file_data)/1024:.1f}KB），最大允许{_MAX_SCRIPT_SIZE/1024:.0f}KB。")
        return

    # 检查扩展名
    _, ext = os.path.splitext(file_name)
    ext = ext.lower()
    if ext not in _ALLOWED_SCRIPT_EXT:
        await exec_cmd.finish(f"...不支持的文件格式 {ext}。\n支持：{', '.join(sorted(_ALLOWED_SCRIPT_EXT))}")
        return

    await exec_cmd.send(f"...收到脚本 `{file_name}`（{len(file_data)/1024:.1f}KB），执行中...")

    # 保存到临时文件
    tmp_dir = tempfile.mkdtemp(prefix="yuuki_exec_")
    # 安全化文件名（防止路径穿越和shell元字符）
    safe_name = os.path.basename(file_name)
    safe_name = re.sub(r'[^\w\.\-]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = "script" + ext
    tmp_file = os.path.join(tmp_dir, safe_name)

    try:
        with open(tmp_file, "wb") as f:
            f.write(file_data)

        # 根据扩展名选择执行方式
        if ext == '.py':
            cmd = f'python "{tmp_file}"'
        elif ext == '.sh':
            cmd = f'bash "{tmp_file}"'
        elif ext == '.bat':
            cmd = f'cmd /c "{tmp_file}"'
        elif ext == '.ps1':
            cmd = f'powershell -File "{tmp_file}"'
        elif ext == '.js':
            cmd = f'node "{tmp_file}"'
        elif ext == '.lua':
            cmd = f'lua "{tmp_file}"'
        elif ext == '.rb':
            cmd = f'ruby "{tmp_file}"'
        elif ext == '.go':
            # 先编译再执行
            cmd = f'cd "{tmp_dir}" && go run "{tmp_file}"'
        else:
            cmd = f'"{tmp_file}"'

        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmp_dir
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_SCRIPT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            await exec_cmd.finish(f"...脚本执行超时（{_SCRIPT_TIMEOUT}秒），已终止。")
            return

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode

        result_parts = []
        if stdout_str:
            result_parts.append(stdout_str)
        if stderr_str:
            result_parts.append(f"[stderr]\n{stderr_str}")

        result = "\n".join(result_parts) if result_parts else "(无输出)"

        if len(result) > _MAX_OUTPUT:
            result = result[:_MAX_OUTPUT] + f"\n...（输出过长，已截断）"

        msg = f"📄 `{file_name}` 退出码：{exit_code}\n{'━' * 20}\n{result}"
        await exec_cmd.finish(msg)

    except Exception as e:
        await exec_cmd.finish(f"...执行出错：{type(e).__name__}: {e}")
    finally:
        # 递归清理临时目录
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


exec_cmd = _register("exec", _cmd_exec, priority=1, admin_only=True)

#!/usr/bin/env python3
"""
结城希亚 - NoneBot2 QQ机器人
项目结构:
├── bot.py              # 入口文件
├── yuuki_bot/          # 核心模块
│   ├── __init__.py
│   ├── config.py       # 配置管理
│   ├── utils.py        # 工具函数
│   └── core/           # 核心组件
├── plugins/            # NoneBot 插件
│   └── yuuki_chat/     # 主插件
└── yuuki_data/         # 数据目录
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter
import os
import json
import logging

# 设置工作目录
current_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(current_dir)

# 初始化 NoneBot
nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

# 加载插件
nonebot.load_plugin("nonebot_plugin_apscheduler")
nonebot.load_plugins(os.path.join(current_dir, "plugins"))

# 配置日志
logger = logging.getLogger("yuuki_bot")

# Sentry 错误追踪（可选）
try:
    import sentry_sdk
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            send_default_pii=True,
            traces_sample_rate=1.0,
        )
        logger.info("[Sentry] 错误追踪已启用")
    else:
        logger.info("[Sentry] 未配置 SENTRY_DSN 环境变量，跳过初始化")
except ImportError:
    logger.info("[Sentry] sentry-sdk 未安装，跳过错误追踪")
except Exception as e:
    logger.error(f"[Sentry] 初始化失败: {e}")

# 重启标记处理
restart_info = None
restart_file = os.path.join(current_dir, "restart_flag.json")

def _load_and_clear_restart():
    """加载并清除重启标记"""
    global restart_info
    if os.path.exists(restart_file):
        try:
            with open(restart_file, "r", encoding="utf-8") as f:
                restart_info = json.load(f)
            logger.info(f"读取到重启信息: {restart_info}")
            os.remove(restart_file)
            logger.info("重启标记文件已清除")
        except Exception as e:
            logger.error(f"读取重启标记失败: {e}")
            try:
                os.remove(restart_file)
            except Exception:
                pass

_load_and_clear_restart()


@driver.on_bot_connect
async def on_bot_connect(bot):
    """Bot 连接成功后的回调"""
    global restart_info
    logger.info(f"Bot 已连接! restart_info: {restart_info}")
    
    if restart_info and isinstance(restart_info, dict):
        try:
            import asyncio
            await asyncio.sleep(2)

            if "group_id" in restart_info:
                logger.info(f"发送群消息到: {restart_info['group_id']}")
                await bot.send_group_msg(
                    group_id=restart_info["group_id"], 
                    message="重启成功!"
                )
            elif "user_id" in restart_info:
                logger.info(f"发送私聊消息到: {restart_info['user_id']}")
                await bot.send_private_msg(
                    user_id=restart_info["user_id"], 
                    message="重启成功!"
                )

            restart_info = None
        except Exception as e:
            logger.error(f"发送重启成功消息失败: {e}")


@driver.on_startup
async def on_startup():
    """启动时执行的初始化任务"""
    logger.info("=" * 60)
    logger.info("结城希亚启动中...")
    logger.info(f"工作目录: {current_dir}")
    logger.info(f"Python版本: {os.sys.version.split()[0]}")
    logger.info("=" * 60)


@driver.on_shutdown
async def on_shutdown():
    """关闭时执行的清理任务"""
    logger.info("=" * 60)
    logger.info("结城希亚正在关闭...")
    logger.info("=" * 60)


if __name__ == "__main__":
    nonebot.run()
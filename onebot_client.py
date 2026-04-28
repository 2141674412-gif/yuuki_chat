"""
OneBot v11 WebSocket 轻量客户端
适用于 NapCat / go-cqhttp 等 OneBot v11 实现
依赖: websockets (pip install websockets)
"""

import asyncio
import json
import logging
import re
import time
from functools import wraps
from typing import Any, Callable, Optional

try:
    import websockets
except ImportError:
    raise ImportError("请先安装 websockets: pip install websockets")


# ============================================================
# 日志配置 (loguru 风格)
# ============================================================

class _LoguruFormatter(logging.Formatter):
    LEVEL_COLORS = {
        "DEBUG": "<cyan>", "INFO": "<green>", "WARNING": "<yellow>",
        "ERROR": "<red>", "CRITICAL": "<bold><red>",
    }

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        color = self.LEVEL_COLORS.get(level, "")
        close = "</>" if color else ""
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        name = record.name.split(".")[-1] if "." in record.name else record.name
        return f"{color}{level:<8}{close} | {ts} | {name}:{record.lineno} | {record.getMessage()}"


def _setup_logger(name: str = "onebot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(_LoguruFormatter())
    logger.addHandler(handler)
    return logger


log = _setup_logger("onebot")


# ============================================================
# 消息段构建工具
# ============================================================

def text(t: str) -> dict:
    """纯文本消息段"""
    return {"type": "text", "data": {"text": t}}

def at(qq: str | int) -> dict:
    """@某人消息段"""
    return {"type": "at", "data": {"qq": str(qq)}}

def face(id_: int) -> dict:
    """QQ 表情消息段"""
    return {"type": "face", "data": {"id": str(id_)}}

def image(file: str = "", url: str = "") -> dict:
    """图片消息段, 通过 file 或 url 指定"""
    if not file and not url:
        raise ValueError("image() 至少需要提供 file 或 url 参数")
    data = {}
    if url: data["url"] = url
    if file: data["file"] = file
    return {"type": "image", "data": data}

def reply(id_: int) -> dict:
    """回复消息段"""
    return {"type": "reply", "data": {"id": str(id_)}}

def json_(data: str) -> dict:
    """JSON 卡片消息段"""
    return {"type": "json", "data": {"data": data}}

def record(file: str = "", url: str = "") -> dict:
    """语音消息段"""
    if not file and not url:
        raise ValueError("record() 至少需要提供 file 或 url 参数")
    data = {}
    if url: data["url"] = url
    if file: data["file"] = file
    return {"type": "record", "data": data}


# ============================================================
# CQ 码解析器
# ============================================================

class CQCode:
    """CQ 码与消息段列表之间的互相转换"""
    _PATTERN = re.compile(r"\[CQ:(\w+)((?:,[^\]]*)?)\]")

    @staticmethod
    def decode(message: str) -> list[dict]:
        """将 CQ 码字符串解析为消息段列表"""
        segments: list[dict] = []
        last_end = 0
        for match in CQCode._PATTERN.finditer(message):
            if match.start() > last_end:
                plain = message[last_end:match.start()]
                if plain:
                    segments.append(text(plain))
            seg_type = match.group(1)
            params_str = match.group(2).lstrip(",")
            data: dict[str, str] = {}
            for pair in params_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    data[k] = v
            segments.append({"type": seg_type, "data": data})
            last_end = match.end()
        if last_end < len(message):
            remaining = message[last_end:]
            if remaining:
                segments.append(text(remaining))
        return segments

    @staticmethod
    def encode(segments: list[dict]) -> str:
        """将消息段列表编码为 CQ 码字符串"""
        parts: list[str] = []
        for seg in segments:
            seg_type = seg.get("type", "text")
            seg_data = seg.get("data", {})
            if seg_type == "text":
                parts.append(seg_data.get("text", ""))
            else:
                params = ",".join(f"{k}={v}" for k, v in seg_data.items())
                parts.append(f"[CQ:{seg_type},{params}]")
        return "".join(parts)

    @staticmethod
    def extract_text(segments: list[dict]) -> str:
        """从消息段列表中提取纯文本内容"""
        return "".join(
            seg["data"].get("text", "") for seg in segments if seg.get("type") == "text"
        )


# ============================================================
# OneBot v11 WebSocket 客户端
# ============================================================

class OneBotClient:
    """
    OneBot v11 WebSocket 客户端
    特性: 自动重连 / 事件分发 / 心跳保活 / CQ 码解析
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:8888/onebot/v11/ws",
        access_token: str = "",
        reconnect_interval: float = 5.0,
        heartbeat_interval: float = 30.0,
    ):
        self.ws_url = ws_url
        self.access_token = access_token
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval
        self._ws = None
        self._running = False
        self._api_futures: dict[str, asyncio.Future] = {}
        self._event_handlers: dict[str, list[Callable]] = {}
        self._echo_counter = 0

    # ----------------------------------------------------------
    # 事件回调注册 (装饰器)
    # ----------------------------------------------------------

    def on(self, event_type: str, sub_type: str = ""):
        """
        事件回调注册装饰器
        用法: @client.on("message", "group") / @client.on("notice", "group_increase")
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(event: dict):
                try:
                    await func(event)
                except Exception as e:
                    log.error(f"事件处理器异常 [{func.__name__}]: {e}")
            wrapper._event_type = event_type
            wrapper._sub_type = sub_type
            self._event_handlers.setdefault(event_type, []).append(wrapper)
            return wrapper
        return decorator

    def on_message(self, sub_type: str = ""):
        """消息事件注册快捷方式"""
        return self.on("message", sub_type)

    def on_notice(self, sub_type: str = ""):
        """通知事件注册快捷方式"""
        return self.on("notice", sub_type)

    def on_request(self, sub_type: str = ""):
        """请求事件注册快捷方式"""
        return self.on("request", sub_type)

    # ----------------------------------------------------------
    # 连接管理
    # ----------------------------------------------------------

    async def connect(self):
        """启动客户端, 连接 WebSocket 并开始事件循环"""
        self._running = True
        log.info(f"正在连接 {self.ws_url} ...")
        # 构建连接参数
        extra_headers = {}
        if self.access_token:
            extra_headers["Authorization"] = f"Bearer {self.access_token}"
        while self._running:
            try:
                async with websockets.connect(self.ws_url, additional_headers=extra_headers) as ws:
                    self._ws = ws
                    log.info("WebSocket 连接成功")
                    await self._recv_loop(ws)
            except (websockets.ConnectionClosed, websockets.InvalidURI, OSError) as e:
                self._ws = None
                if not self._running:
                    break
                log.warning(f"连接断开: {e}, {self.reconnect_interval}s 后重连...")
                await asyncio.sleep(self.reconnect_interval)

    async def disconnect(self):
        """断开连接并停止事件循环"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        log.info("已断开连接")

    # ----------------------------------------------------------
    # 接收循环与事件分发
    # ----------------------------------------------------------

    async def _recv_loop(self, ws):
        """消息接收主循环"""
        hb_task = asyncio.create_task(self._heartbeat_loop(ws)) if self.heartbeat_interval > 0 else None
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning(f"收到无效 JSON: {raw[:200]}")
                    continue
                # API 响应
                if "echo" in data:
                    future = self._api_futures.pop(data["echo"], None)
                    if future and not future.done():
                        if data.get("status") == "failed":
                            future.set_exception(RuntimeError(data.get("wording", "API 调用失败")))
                        else:
                            future.set_result(data.get("data"))
                    continue
                # 事件分发
                await self._dispatch(data.get("post_type", ""), data)
        except websockets.ConnectionClosed:
            log.warning("WebSocket 连接已关闭")
        finally:
            if hb_task:
                hb_task.cancel()

    async def _dispatch(self, post_type: str, event: dict):
        """根据 post_type 分发事件到对应的处理器"""
        for handler in self._event_handlers.get(post_type, []):
            sub_type = getattr(handler, "_sub_type", "")
            if sub_type and event.get("sub_type") != sub_type:
                continue
            asyncio.create_task(handler(event))
        if post_type not in self._event_handlers and post_type != "meta_event":
            log.debug(f"未处理事件: {post_type} - {event}")

    async def _heartbeat_loop(self, ws):
        """心跳保活循环"""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await ws.send(json.dumps({"echo": "heartbeat"}))
                log.debug("发送心跳")
            except Exception:
                break

    # ----------------------------------------------------------
    # API 调用
    # ----------------------------------------------------------

    async def _call_api(self, action: str, **params) -> Any:
        """调用 OneBot API, 返回 data 字段内容"""
        if not self._ws:
            raise RuntimeError("WebSocket 未连接")
        self._echo_counter += 1
        echo = f"api_{self._echo_counter}_{int(time.time())}"
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._api_futures[echo] = future
        await self._ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._api_futures.pop(echo, None)
            raise TimeoutError(f"API 调用超时: {action}")

    async def send_group_msg(self, group_id: int, message: str | list[dict]) -> dict:
        """发送群消息, message 可以是 CQ 码字符串或消息段列表"""
        if isinstance(message, str):
            message = CQCode.decode(message)
        return await self._call_api("send_group_msg", group_id=group_id, message=message)

    async def send_private_msg(self, user_id: int, message: str | list[dict]) -> dict:
        """发送私聊消息"""
        if isinstance(message, str):
            message = CQCode.decode(message)
        return await self._call_api("send_private_msg", user_id=user_id, message=message)

    async def send_group_forward_msg(self, group_id: int, nodes: list[dict]) -> dict:
        """
        发送群合并转发消息
        nodes: 转发节点列表, 使用 forward_node() 构建
        """
        return await self._call_api("send_group_forward_msg", group_id=group_id, messages=nodes)

    async def get_login_info(self) -> dict:
        """获取登录号信息"""
        return await self._call_api("get_login_info")

    async def get_group_list(self) -> list[dict]:
        """获取群列表"""
        return await self._call_api("get_group_list")


# ============================================================
# 辅助函数
# ============================================================

def forward_node(uin: int, name: str, content: str | list[dict]) -> dict:
    """构建合并转发节点, content 可以是 CQ 码字符串或消息段列表"""
    if isinstance(content, str):
        content = CQCode.decode(content)
    return {"type": "node", "data": {"uin": str(uin), "name": name, "content": content}}


# ============================================================
# 示例用法
# ============================================================

async def example():
    """
    示例: 连接 NapCat, 注册事件处理器, 发送消息
    使用前请确保 NapCat 已启动并开启 WebSocket 服务
    """
    client = OneBotClient(
        ws_url="ws://127.0.0.1:8888/onebot/v11/ws",
        access_token="c196c4395ca8",  # NapCat access_token
        reconnect_interval=5.0,
        heartbeat_interval=30.0,
    )

    # --- 注册事件处理器 ---

    @client.on("message")
    async def on_any_message(event: dict):
        sender = event.get("sender", {})
        log.info(f"[{sender.get('nickname', '未知')}] 收到消息")

    @client.on_message("group")
    async def on_group_message(event: dict):
        group_id = event.get("group_id")
        user_id = event.get("user_id")
        raw_msg = event.get("raw_message", "")
        log.info(f"群 {group_id} | {user_id}: {raw_msg}")

        # 解析消息段, 提取纯文本
        segments = event.get("message", [])
        if isinstance(segments, str):
            segments = CQCode.decode(segments)
        plain_text = CQCode.extract_text(segments)

        # 收到 "ping" 回复 "pong"
        if plain_text.strip() == "ping":
            await client.send_group_msg(group_id, "pong")

        # 收到 "图" 发送图片
        if plain_text.strip() == "图":
            await client.send_group_msg(group_id, [
                text("这是一张图片:\n"),
                image(url="https://example.com/demo.jpg"),
            ])

    @client.on_notice("group_increase")
    async def on_group_increase(event: dict):
        group_id = event.get("group_id")
        user_id = event.get("user_id")
        log.info(f"群 {group_id} 有新成员加入: {user_id}")
        await client.send_group_msg(group_id, [at(user_id), text(" 欢迎加入本群!")])

    @client.on_request("friend")
    async def on_friend_request(event: dict):
        log.info(f"收到好友请求: {event.get('user_id')}")

    # --- 启动连接 ---
    connect_task = asyncio.create_task(client.connect())
    # 等待连接成功（最多10秒）
    for _ in range(20):
        await asyncio.sleep(0.5)
        if client._ws is not None:
            break
    else:
        log.error("连接超时，请检查NapCat是否启动")
        return

    try:
        info = await client.get_login_info()
        log.info(f"登录账号: {info}")

        # 发送群消息 (取消注释后使用)
        # await client.send_group_msg(123456789, [text("Hello!"), at(12345)])

        # 发送合并转发
        # nodes = [
        #     forward_node(10001, "Alice", "第一条消息"),
        #     forward_node(10002, "Bob", [text("第二条"), image(url="https://example.com/img.png")]),
        # ]
        # await client.send_group_forward_msg(123456789, nodes)

        # CQ 码解析示例
        cq_str = "[CQ:at,qq=12345]你好[CQ:face,id=178]世界"
        segments = CQCode.decode(cq_str)
        log.info(f"CQ 解码: {segments}")
        log.info(f"CQ 编码: {CQCode.encode(segments)}")

        await connect_task  # 保持运行
    except KeyboardInterrupt:
        log.info("正在退出...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(example())

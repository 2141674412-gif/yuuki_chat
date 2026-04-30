"""MQTT 远程设备控制命令（仅管理员）"""
import threading
import asyncio
from nonebot import get_bot
from nonebot.adapters.onebot.v11 import MessageEvent

# MQTT配置
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

# ESP32控制主题（匹配你的ESP32代码）
DEFAULT_TOPIC = "esp32/receive"

# 总开关（默认关闭，需要管理员手动开启）
_mqtt_enabled = False

# MQTT客户端（懒加载）
_mqtt_client = None
_mqtt_connected = False
_mqtt_lock = threading.Lock()

async def _send(event, msg):
    """发送消息"""
    bot = get_bot()
    if hasattr(event, 'group_id'):
        await bot.send_group_msg(group_id=event.group_id, message=msg)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=msg)

def _get_mqtt_client():
    """获取或创建MQTT客户端"""
    global _mqtt_client, _mqtt_connected
    with _mqtt_lock:
        if _mqtt_client is None or not _mqtt_connected:
            try:
                import paho.mqtt.client as mqtt
                _mqtt_client = mqtt.Client()
                _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
                _mqtt_client.loop_start()
                _mqtt_connected = True
            except Exception as e:
                _mqtt_connected = False
                raise e
        return _mqtt_client

async def _mqtt_publish(topic: str, message: str) -> bool:
    """发布MQTT消息"""
    try:
        client = await asyncio.get_event_loop().run_in_executor(None, _get_mqtt_client)
        result = client.publish(topic, message)
        return result.rc == 0
    except Exception:
        return False

# ========== 总开关 ==========

async def _cmd_mqtt_on(event: MessageEvent):
    """开启MQTT控制"""
    global _mqtt_enabled
    _mqtt_enabled = True
    await _send(event, "...MQTT控制已开启 ✅\n可用命令：/开风扇 /关风扇 /风速 /风扇状态 /mqtt")

async def _cmd_mqtt_off(event: MessageEvent):
    """关闭MQTT控制"""
    global _mqtt_enabled
    _mqtt_enabled = False
    await _send(event, "...MQTT控制已关闭 🔒")

# ========== 风扇控制命令 ==========

async def _cmd_fan_on(event: MessageEvent):
    """开风扇"""
    if not _mqtt_enabled:
        await _send(event, "...MQTT控制未开启，请管理员先 /mqtt开")
        return
    success = await _mqtt_publish(DEFAULT_TOPIC, "启动")
    if success:
        await _send(event, "...风扇已启动。")
    else:
        await _send(event, "...MQTT连接失败，请检查网络。")

async def _cmd_fan_off(event: MessageEvent):
    """关风扇"""
    if not _mqtt_enabled:
        await _send(event, "...MQTT控制未开启，请管理员先 /mqtt开")
        return
    success = await _mqtt_publish(DEFAULT_TOPIC, "停止")
    if success:
        await _send(event, "...风扇已停止。")
    else:
        await _send(event, "...MQTT连接失败，请检查网络。")

async def _cmd_fan_speed(event: MessageEvent):
    """调速风扇：/风速 128"""
    if not _mqtt_enabled:
        await _send(event, "...MQTT控制未开启，请管理员先 /mqtt开")
        return
    content = str(event.message).strip()
    for prefix in ["风速", "调速", "fanspeed"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break
    if not content:
        await _send(event, "...格式：/风速 0-255")
        return
    try:
        speed = int(content)
        speed = max(0, min(255, speed))
        success = await _mqtt_publish(DEFAULT_TOPIC, str(speed))
        if success:
            pct = int(speed / 255.0 * 100)
            await _send(event, f"...风速已调至 {speed}/255 ({pct}%)")
        else:
            await _send(event, "...MQTT连接失败。")
    except ValueError:
        await _send(event, "...请输入0-255的数字。")

async def _cmd_fan_status(event: MessageEvent):
    """查询风扇状态"""
    if not _mqtt_enabled:
        await _send(event, "...MQTT控制未开启，请管理员先 /mqtt开")
        return
    success = await _mqtt_publish(DEFAULT_TOPIC, "状态")
    if success:
        await _send(event, "...已查询风扇状态。")
    else:
        await _send(event, "...MQTT连接失败。")

# ========== 通用发布 ==========

async def _cmd_mqtt(event: MessageEvent):
    """通用MQTT发布：/mqtt 主题 消息"""
    content = str(event.message).strip()
    for prefix in ["mqtt", "MQTT"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _send(event, "...格式：/mqtt 主题 消息\n"
                         "示例：\n"
                         "  /mqtt esp32/receive 启动\n"
                         "  /mqtt esp32/receive 128\n"
                         "  /mqtt esp32/receive 状态")
        return

    if not _mqtt_enabled:
        await _send(event, "...MQTT控制未开启，请管理员先 /mqtt开")
        return

    # 第一个空格分隔主题和消息
    parts = content.split(None, 1)
    if len(parts) < 2:
        await _send(event, "...需要指定主题和消息。")
        return

    topic, message = parts[0], parts[1]
    success = await _mqtt_publish(topic, message)
    if success:
        await _send(event, f"...已发送到 {topic}: {message}")
    else:
        await _send(event, "...MQTT连接失败。")

# ========== 注册命令（全部仅管理员） ==========
from .commands_base import _register

mqtt_on_cmd = _register("mqtt开", _cmd_mqtt_on, aliases=["MQTT开", "mqtt开启"], admin_only=True)
mqtt_off_cmd = _register("mqtt关", _cmd_mqtt_off, aliases=["MQTT关", "mqtt关闭"], admin_only=True)
fan_on_cmd = _register("开风扇", _cmd_fan_on, aliases=["风扇开", "fan_on", "开电机", "电机开"], admin_only=True)
fan_off_cmd = _register("关风扇", _cmd_fan_off, aliases=["风扇关", "fan_off", "关电机", "电机关"], admin_only=True)
fan_speed_cmd = _register("风速", _cmd_fan_speed, aliases=["调速", "fanspeed"], admin_only=True)
fan_status_cmd = _register("风扇状态", _cmd_fan_status, aliases=["电机状态", "fan_status"], admin_only=True)
mqtt_cmd = _register("mqtt", _cmd_mqtt, aliases=["MQTT"], admin_only=True)

"""MQTT 远程设备控制命令"""
import json
import threading
import asyncio
from nonebot import on_command, get_driver
from nonebot.adapters.onebot.v11 import MessageEvent, Bot

# MQTT配置
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

# 默认控制主题
DEFAULT_TOPIC = "yuuki/motor/control"

# MQTT客户端（懒加载）
_mqtt_client = None
_mqtt_connected = False
_mqtt_lock = threading.Lock()

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
    except Exception as e:
        return False

# ========== 固定命令 ==========

async def _cmd_motor_on(event: MessageEvent):
    """开电机"""
    success = await _mqtt_publish(DEFAULT_TOPIC, json.dumps({"action": "on"}, ensure_ascii=False))
    if success:
        await _send(event, "...电机已开启。")
    else:
        await _send(event, "...MQTT连接失败，请检查网络。")

async def _cmd_motor_off(event: MessageEvent):
    """关电机"""
    success = await _mqtt_publish(DEFAULT_TOPIC, json.dumps({"action": "off"}, ensure_ascii=False))
    if success:
        await _send(event, "...电机已关闭。")
    else:
        await _send(event, "...MQTT连接失败，请检查网络。")

# ========== 通用发布 ==========

async def _cmd_mqtt(event: MessageEvent):
    """通用MQTT发布：/mqtt 主题 消息"""
    content = str(event.message).strip()
    for prefix in ["mqtt", "MQTT"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    if not content:
        await _send(event, "...格式：/mqtt 主题 消息\n示例：/mqtt yuuki/motor/control {\"action\":\"on\"}")
        return

    # 第一个空格分隔主题和消息
    parts = content.split(None, 1)
    if len(parts) < 2:
        await _send(event, "...需要指定主题和消息。")
        return

    topic, message = parts[0], parts[1]
    success = await _mqtt_publish(topic, message)
    if success:
        await _send(event, f"...已发送到 {topic}")
    else:
        await _send(event, "...MQTT连接失败。")

# ========== 注册命令 ==========
from .commands_base import _register, _send

motor_on_cmd = _register("开电机", _cmd_motor_on, aliases=["电机开", "motor_on"])
motor_off_cmd = _register("关电机", _cmd_motor_off, aliases=["电机关", "motor_off"])
mqtt_cmd = _register("mqtt", _cmd_mqtt, aliases=["MQTT"])

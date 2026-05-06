"""
配置管理模块
提供统一的配置读取和管理功能
"""

import os
import json
import logging

logger = logging.getLogger("yuuki_bot.config")

# 默认配置
DEFAULT_CONFIG = {
    "api_base": "https://open.bigmodel.cn/api/paas/v4",
    "api_key": "",
    "model_name": "glm-4-flash",
    "max_tokens": 1024,
    "temperature": 0.8,
    "bot_name": "结城希亚",
    "creator_name": "主人",
    "allowed_groups": [],
    "superusers": [],
    "local_cover_dir": "",
    "update_url": "https://github.com/2141674412-gif/yuuki_chat/releases/latest/download/yuuki_chat.zip",
}


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        # 从环境变量读取
        env_config = self._load_from_env()
        self._config.update(env_config)
        
        # 从配置文件读取
        config_path = os.path.join(os.getcwd(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                    self._config.update(file_config)
                logger.info(f"已加载配置文件: {config_path}")
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
    
    def _load_from_env(self):
        """从环境变量读取配置"""
        env_map = {
            "API_BASE": "api_base",
            "API_KEY": "api_key",
            "MODEL_NAME": "model_name",
            "MAX_TOKENS": "max_tokens",
            "TEMPERATURE": "temperature",
            "BOT_NAME": "bot_name",
            "CREATOR_NAME": "creator_name",
            "LOCAL_COVER_DIR": "local_cover_dir",
            "UPDATE_URL": "update_url",
        }
        
        result = {}
        for env_key, config_key in env_map.items():
            value = os.environ.get(env_key)
            if value is not None:
                if config_key in ["max_tokens", "temperature"]:
                    try:
                        result[config_key] = int(value) if config_key == "max_tokens" else float(value)
                    except ValueError:
                        pass
                else:
                    result[config_key] = value
        
        # 处理列表类型的环境变量
        allowed_groups = os.environ.get("ALLOWED_GROUPS", "")
        if allowed_groups:
            result["allowed_groups"] = [self._safe_int(g.strip()) for g in allowed_groups.split(",") if g.strip()]
        
        superusers = os.environ.get("SUPERUSERS", "")
        if superusers:
            result["superusers"] = [self._safe_int(s.strip()) for s in superusers.split(",") if s.strip()]
        
        return result
    
    def _safe_int(self, value, default=0):
        """安全转换整数"""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    def get(self, key, default=None):
        """获取配置值"""
        return self._config.get(key, default)
    
    def set(self, key, value):
        """设置配置值"""
        self._config[key] = value
    
    def save(self, path=None):
        """保存配置到文件"""
        if path is None:
            path = os.path.join(os.getcwd(), "config.json")
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
            logger.info(f"配置已保存到: {path}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False
    
    def __getitem__(self, key):
        return self._config[key]
    
    def __setitem__(self, key, value):
        self._config[key] = value
    
    def __contains__(self, key):
        return key in self._config


# 创建全局配置实例
config = ConfigManager()


def get_api_key():
    """获取 API Key"""
    return config.get("api_key", "")


def get_api_base():
    """获取 API 基础地址"""
    return config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")


def get_model_name():
    """获取模型名称"""
    return config.get("model_name", "glm-4-flash")


def get_bot_name():
    """获取 Bot 名称"""
    return config.get("bot_name", "结城希亚")


def get_creator_name():
    """获取创作者名称"""
    return config.get("creator_name", "主人")


def is_superuser(user_id):
    """检查是否为超级管理员"""
    superusers = config.get("superusers", [])
    return str(user_id) in [str(s) for s in superusers]


def is_group_allowed(group_id):
    """检查群是否在白名单中"""
    allowed_groups = config.get("allowed_groups", [])
    if not allowed_groups:
        return True  # 白名单为空时允许所有群
    return group_id in allowed_groups
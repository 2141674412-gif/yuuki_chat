"""
命令模块
包含所有命令的注册和管理
"""

__all__ = [
    "CommandRegistry",
    "register_command",
    "get_command",
    "list_commands",
]


class CommandRegistry:
    """命令注册器"""
    
    def __init__(self):
        self._commands = {}
        self._aliases = {}
    
    def register(self, name, handler, aliases=None, priority=5, admin_only=False):
        """注册命令"""
        if name in self._commands:
            raise ValueError(f"命令 '{name}' 已存在")
        
        self._commands[name] = {
            "handler": handler,
            "aliases": aliases or [],
            "priority": priority,
            "admin_only": admin_only,
        }
        
        # 注册别名
        for alias in aliases or []:
            if alias in self._aliases:
                raise ValueError(f"别名 '{alias}' 已被使用")
            self._aliases[alias] = name
    
    def get(self, name):
        """获取命令信息"""
        # 首先检查别名
        if name in self._aliases:
            name = self._aliases[name]
        
        return self._commands.get(name)
    
    def list(self):
        """获取所有命令列表"""
        return list(self._commands.keys())
    
    def list_with_details(self):
        """获取所有命令详情"""
        return self._commands
    
    def is_admin_command(self, name):
        """检查命令是否需要管理员权限"""
        cmd = self.get(name)
        return cmd.get("admin_only", False) if cmd else False


# 创建全局命令注册器
_command_registry = CommandRegistry()


def register_command(name, handler, aliases=None, priority=5, admin_only=False):
    """注册命令（简化接口）"""
    _command_registry.register(name, handler, aliases, priority, admin_only)


def get_command(name):
    """获取命令"""
    return _command_registry.get(name)


def list_commands():
    """列出所有命令"""
    return _command_registry.list()


def list_commands_with_details():
    """列出所有命令详情"""
    return _command_registry.list_with_details()


def is_admin_command(name):
    """检查是否为管理员命令"""
    return _command_registry.is_admin_command(name)
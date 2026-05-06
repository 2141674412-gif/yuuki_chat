"""
核心模块
包含 Bot 的核心功能组件
"""

__all__ = [
    "BotCore",
    "MessageHandler",
    "TaskScheduler",
    "DataManager",
]


class BotCore:
    """Bot 核心类"""
    
    def __init__(self):
        self._initialized = False
        self._handlers = []
    
    def initialize(self):
        """初始化核心模块"""
        if self._initialized:
            return
        
        # 兼容处理：core 模块下的子模块不存在时跳过
        try:
            from .config import config
            from .utils import ensure_dir
            
            # 确保数据目录存在
            ensure_dir(config.get("data_dir", "yuuki_data"))
        except ImportError:
            pass
        
        self._initialized = True
    
    def register_handler(self, handler):
        """注册消息处理器"""
        self._handlers.append(handler)
    
    async def process_message(self, event):
        """处理消息"""
        for handler in self._handlers:
            if await handler.can_handle(event):
                await handler.handle(event)
                return True
        return False


class MessageHandler:
    """消息处理器基类"""
    
    def __init__(self):
        self._priority = 5
    
    @property
    def priority(self):
        """优先级"""
        return self._priority
    
    async def can_handle(self, event):
        """判断是否能处理该消息"""
        raise NotImplementedError
    
    async def handle(self, event):
        """处理消息"""
        raise NotImplementedError


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self):
        self._tasks = []
    
    def add_task(self, task):
        """添加任务"""
        self._tasks.append(task)
    
    def remove_task(self, task_id):
        """移除任务"""
        self._tasks = [t for t in self._tasks if t.id != task_id]
    
    def get_tasks(self):
        """获取所有任务"""
        return self._tasks
    
    async def run_pending(self):
        """运行待执行的任务"""
        for task in self._tasks:
            if task.is_due():
                await task.execute()


class DataManager:
    """数据管理器"""
    
    def __init__(self):
        self._stores = {}
    
    def register_store(self, name, store):
        """注册数据存储"""
        self._stores[name] = store
    
    def get_store(self, name):
        """获取数据存储"""
        return self._stores.get(name)
    
    async def backup_all(self):
        """备份所有数据"""
        for name, store in self._stores.items():
            await store.backup()
    
    async def restore_all(self, backup_path):
        """恢复所有数据"""
        for name, store in self._stores.items():
            await store.restore(backup_path)


# 创建全局实例
bot_core = BotCore()
task_scheduler = TaskScheduler()
data_manager = DataManager()

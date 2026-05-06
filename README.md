# Yuuki Bot - 结城希亚

> 玖方女学院2年生，瓦尔哈拉社领导人。正义的伙伴。

## 📁 项目结构

```
yuuki-bot/
├── bot.py              # 入口文件
├── requirements.txt    # 依赖列表
├── .env.example        # 环境变量示例
├── .gitignore          # Git 忽略配置
├── migrate_data.py     # 数据迁移脚本
├── yuuki_bot/          # 核心模块（新增）
│   ├── __init__.py
│   ├── config.py       # 配置管理
│   ├── utils.py        # 工具函数
│   ├── core/           # 核心组件
│   │   └── __init__.py
│   ├── commands/       # 命令管理
│   │   └── __init__.py
│   ├── data/           # 数据存储
│   └── assets/         # 资源文件
├── plugins/            # NoneBot 插件
│   └── yuuki_chat/     # 主插件（原有）
└── yuuki_data/         # 数据目录（运行时创建）
```

## 🚀 快速开始

### 1. 安装依赖

```bash
# 使用虚拟环境
f:\chat\yuuki-bot\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并修改配置：

```bash
# Windows
copy .env.example .env

# Linux/macOS
cp .env.example .env
```

编辑 `.env` 文件，设置以下关键配置：
- `API_KEY` - 智谱API密钥
- `SUPERUSERS` - 超级管理员QQ号

### 3. 数据迁移（首次运行）

如果是从旧版本升级，执行数据迁移：

```bash
python migrate_data.py
```

### 4. 启动 Bot

```bash
# 使用虚拟环境启动
f:\chat\yuuki-bot\venv\Scripts\python.exe bot.py
```

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_KEY` | 智谱API密钥 | 空 |
| `API_BASE` | API地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `MODEL_NAME` | 模型名称 | `glm-4-flash` |
| `MAX_TOKENS` | 最大Token数 | `1024` |
| `TEMPERATURE` | 温度参数 | `0.8` |
| `SUPERUSERS` | 超级管理员（逗号分隔） | 空 |
| `ALLOWED_GROUPS` | 允许的群（逗号分隔） | 空（允许所有） |
| `SENTRY_DSN` | Sentry错误追踪 | 空 |

### 配置文件

也可以在 `config.json` 中配置：

```json
{
  "api_key": "your_api_key",
  "superusers": ["123456789"],
  "allowed_groups": [123456789]
}
```

## 📜 命令列表

### 日常命令
- `/签到(qd)` - 每日签到
- `/积分(jf)` - 查询积分
- `/排行(ph)` - 积分排行
- `/人设(rs)` - 查看人设
- `/好感度(hgd)` - 查好感度

### 工具命令
- `/天气(tq)` - 查询天气
- `/翻译(fy)` - 翻译内容
- `/计算器(jsq)` - 计算表达式
- `/搜索(ss)` - 搜索
- `/提醒(tx)` - 设置提醒

### 趣味命令
- `/抽签(cq)` - 抽签
- `/运势(ys)` - 今日运势
- `/成语(cy)` - 成语接龙
- `/笑话(xh)` - 随机笑话
- `/点歌(dg)` - 点歌

### 舞萌DX
- `/mai(舞萌) b50` - 查询B50
- `/牌子(pz)` - 查询牌子进度
- `/绑定(bd)` - 绑定好友码

### 管理命令（仅管理员）
- `/更新` - 自动更新
- `/重启` - 重启Bot
- `/诊断` - 系统诊断
- `/拉黑` - 添加黑名单
- `/加群` - 添加允许群

## 🛠️ 开发

### 核心模块

```python
from yuuki_bot import config, utils, core

# 配置管理
api_key = config.get("api_key")

# 工具函数
hash = utils.calc_file_hash("file.txt")

# 核心组件
core.bot_core.initialize()
```

## 📝 版本历史

### v2.5.0
- 重构项目结构
- 添加核心模块
- 统一配置管理
- 优化命令注册

### v2.0.0
- 初始版本

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 PR！

---

*结城希亚 - 正义的伙伴* ✨
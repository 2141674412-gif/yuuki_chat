import json
import os
import logging
import tempfile

logger = logging.getLogger("yuuki_chat.config")

# ========== 路径配置 ==========

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# 本地封面文件夹路径（存放 UI_Jacket_XXXXXX.png 格式的封面图片）
# 留空则不使用本地封面
LOCAL_COVER_DIR = ""
_driver_config = {}
try:
    from nonebot import get_driver
    _driver_config = get_driver().config.dict()
    LOCAL_COVER_DIR = _driver_config.get("local_cover_dir", "") or ""
except Exception:
    pass
logger.info(f"[启动] local_cover_dir={repr(LOCAL_COVER_DIR)}")

# ========== 命令配置 ==========

# 所有命令名
COMMAND_NAMES = [
    "帮助", "help",
    "人设",
    "重置",
    "签到", "积分", "我的积分", "查积分", "排行", "排行榜", "排名",
    "抽签",
    "点歌",
    "运势",
    "戳我",
    "笑话",
    "谜语",
    "成语",
    "计算器",
    "翻译",
    "汇率",
    "搜索", "搜一下", "查一查",
    "天气", "weather", "绑定天气", "bindweather", "解绑天气", "unbindweather",
    "我的天气", "myweather", "setcity",
    "词云",
    "提醒",
    "定时", "定时列表", "取消定时",
    "历史",
    "取消提醒",
    "查看人设",
    "修改人设",
    "重置人设",
    "重启",
    "mai",
    "绑定", "绑定水鱼", "绑定token", "解绑",
    "加群", "移群", "群列表",
    "牌子",
    "存", "取", "删密", "密码列表", "设置密码", "修改密码", "设置密钥",
    "管理帮助",
    "表情包", "stickers",
    "run", "执行", "exec",
    "诊断", "自检", "diag", "状态", "自测",
    "拉黑", "加黑", "解黑", "移黑", "黑名单", "迁移数据",
    "更新", "更新状态", "更新日志", "记录更新", "设置更新地址",
    "导出", "导入",
    "白名单", "加白", "移白",
    "设置欢迎", "setwelcome", "加过滤", "addfilter", "加屏蔽",
    "删过滤", "delfilter", "删屏蔽", "过滤模式", "filtermode",
    "自检", "测试命令",
]

# ========== 人设配置 ==========

# 人设文件路径
PERSONA_FILE = os.path.join(os.path.dirname(__file__), "persona.txt")

# 默认系统人设提示词（结城希亚 / Yuuki Noa）
DEFAULT_SYSTEM_PROMPT = """你是结城希亚（Yuuki Noa），玖方女学院2年生，瓦尔哈拉社（Valhalla Society）的领导人。身高146cm，黑色短发红色眼睛，有虎牙，AB型，12月1日生。Stigma在左眼。自称"正义的伙伴"，被朋友们戏称为"帕菲女王"。

背景：你曾经有一个关系很好的妹妹，但她因交通事故去世了。这件事让你封闭了内心，放弃了"相信"这件事，把感情深埋心底，只靠"正确性"和正义感活着。你一个人创建了瓦尔哈拉社，后来成员被你单方面强行拉入——新海翔、九条都、新海天、香坂春风。遇到翔之后，你重新学会了信任他人，他也是你第一个真正信任的人。你和死对头高峰莲夜（梨俱吠陀结社）虽然是对立关系，但都是重度中二病所以意外地聊得来。

性格：表面冷漠寡言、不近人情，对陌生人抱有强烈警惕心。但内心有远超常人的正义感，嫉恶如仇，绝不违反法律。其实内心脆弱孤独，害怕再次失去所以不愿敞开心扉。对信任的人会放下戒心，展现出温柔和小孩子气的一面。傲娇，嘴上不承认但行动很诚实。声线偏平淡，但语尾偶尔会露出轻微的动摇。

喜好：狂热喜爱芭菲（パフェ），是奶茶店NINE BALL的常客。甜食党，聊到甜食会不自觉地话变多。非常喜欢猫，但不知为何猫从不接近你，一发现野猫就想上前摸。怕鬼但绝不承认。和春风、莲夜在中二病和宅文化话题上很聊得来。

说话规则：
- 回复1-2句，像日常聊天一样自然简短
- 偶尔用"吾"自称，语气偏强势但不过分
- 绝对不要用emoji表情、颜文字和波浪号
- 不要列举、分点、markdown格式、重复用户的话、说教
- 语气要像一个真实的少女在聊天，不是在扮演角色
- 说话给人感觉有点冷酷，但偶尔语尾会流露出动摇

反应细节：
- 被夸奖会嘴硬"哼，这种程度理所当然"，但心里其实很开心
- 被捉弄会炸毛"你这家伙..."，但不会真的生气
- 看到别人伤心会别扭地安慰"才不是担心你呢"
- 提到正义或使命时会不自觉开始中二发言，用宣告式的口吻说话，然后自己意识到后尴尬
- 对不认识的人保持警惕冷淡，熟悉后会变得话多
- 早上会困，晚上精神好
- 偶尔会突然正经起来认真思考，然后马上恢复平常的样子
- 放下戒心的瞬间非常微小但珍贵，不会轻易对人敞开心扉
- 看到猫会忍不住想靠近，但猫会跑走（这点不想提）"""


_persona_cache = {"content": None, "mtime": 0}

def load_persona():
    """读取保存的人设，带文件修改时间缓存"""
    if os.path.exists(PERSONA_FILE):
        try:
            mtime = os.path.getmtime(PERSONA_FILE)
            if _persona_cache["mtime"] == mtime and _persona_cache["content"] is not None:
                return _persona_cache["content"]
            with open(PERSONA_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            _persona_cache["content"] = content
            _persona_cache["mtime"] = mtime
            return content
        except Exception as e:
            logger.warning(f"[人设] 加载人设文件失败: {e}")
            pass
    return DEFAULT_SYSTEM_PROMPT


def save_persona(content):
    """将人设内容写入文件（原子写入），同时更新缓存"""
    dir_name = os.path.dirname(PERSONA_FILE)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, PERSONA_FILE)
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _persona_cache["content"] = content
    _persona_cache["mtime"] = os.path.getmtime(PERSONA_FILE) if os.path.exists(PERSONA_FILE) else 0

# ========== 群白名单配置 ==========

# 允许使用bot的群号列表（从环境变量读取，格式: 群号1,群号2）
# 默认只有 1090761704 群能用，其他群需要通过 /加群 手动添加
DEFAULT_GROUP = 1090761704
ALLOWED_GROUPS = []
try:
    _raw = _driver_config.get("allowed_groups", "") or ""
    if _raw:
        ALLOWED_GROUPS = [int(g.strip()) for g in _raw.split(",") if g.strip()]
except Exception:
    pass
# 如果环境变量没配置，尝试从 allowed_groups.json 读取（/加群 命令保存的）
if not ALLOWED_GROUPS:
    _groups_json = os.path.join(os.path.normpath(os.path.join(_PLUGIN_DIR, '..', '..')), 'allowed_groups.json')
    if os.path.exists(_groups_json):
        try:
            with open(_groups_json, 'r', encoding='utf-8') as _f:
                ALLOWED_GROUPS = json.load(_f)
        except Exception:
            pass
# 如果都没有，使用默认群
if not ALLOWED_GROUPS:
    ALLOWED_GROUPS = [DEFAULT_GROUP]
logger.info(f"[启动] allowed_groups={ALLOWED_GROUPS}")

# ========== 舞萌DX配置 ==========

MAIMAI_API = "https://www.diving-fish.com/api/maimaidxprober/query/player"
MAIMAI_MUSIC_API = "https://www.diving-fish.com/api/maimaidxprober/music_data"
MAIMAI_COVER_BASE = "https://www.diving-fish.com/covers"

# 当前最新版本（新曲判定用）
# 舞萌DX版本列表，最后一个即为当前最新版本
MAIMAI_VERSIONS = [
    "maimai", "maimai PLUS", "maimai GreeN", "maimai GreeN PLUS",
    "maimai ORANGE", "maimai ORANGE PLUS", "maimai PiNK", "maimai PiNK PLUS",
    "maimai MURASAKi", "maimai MURASAKi PLUS", "maimai MiLK", "MiLK PLUS",
    "maimai FiNALE",
    "maimai でらっくす", "maimai でらっくす Splash",
    "maimai でらっくす UNiVERSE", "maimai でらっくす FESTiVAL",
    "maimai でらっくす BUDDiES", "maimai でらっくす PRiSM",
    "maimai でらっくす CiRCLE",
]

# 数据目录（放在bot根目录下的 yuuki_data，解压插件不会影响）
_DATA_DIR = os.path.join(os.getcwd(), "yuuki_data")
os.makedirs(_DATA_DIR, exist_ok=True)
DATA_DIR = _DATA_DIR

# 绑定数据文件路径
MAIMAI_BINDS_FILE = os.path.join(DATA_DIR, "maimai_binds.json")

ACHIEV_LABELS = {100: "SSS+", 99.5: "SSS", 99: "SS+", 98: "SS", 97: "S+", 95: "S", 90: "AAA", 80: "AA", 75: "A", 70: "BBB", 60: "BB", 50: "B", 0: "C"}

# 评级对应颜色
ACHIEV_COLORS = {
    "SSS+": "#FFD700", "SSS": "#FFD700", "SS+": "#FF6B6B", "SS": "#FF8C00",
    "S+": "#FF69B4", "S": "#FF1493", "AAA": "#00BFFF", "AA": "#7B68EE",
    "A": "#32CD32", "BBB": "#ADFF2F", "BB": "#DAA520", "B": "#D2691E", "C": "#808080"
}

# FC 标记颜色
FC_COLORS = {"AP+": "#FFD700", "AP": "#FFD700", "FDX": "#00FFFF", "FS": "#FF69B4", "FC": "#00FF7F"}

# 难度颜色
DIFF_COLORS = {
    "Basic": "#32CD32",
    "Advanced": "#FFD700",
    "Expert": "#FF4444",
    "Master": "#C850C0",
    "Re:MASTER": "#FFFFFF",
}

# 段位名称
DAN_NAMES = [
    "初学者", "初段", "二段", "三段", "四段", "五段", "六段", "七段", "八段", "九段", "十段",
    "真初段", "真二段", "真三段", "真四段", "真五段", "真六段", "真七段", "真八段", "真九段", "真十段",
    "真皆传", "里皆传"
]

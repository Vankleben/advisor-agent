"""LLM 客户端与模型表的唯一来源。

此前每个工具各自复制一份模型表、各自 new 一个 OpenAI 客户端（11 处副本、10 处建连），
导致同一类任务在不同入口用了不同模型。需要 LLM 的模块一律从这里取，禁止再抄模型表。

角色（role）语义——按上下文长度而非功能命名，改模型只动本文件：
    fast —— 短任务：阅读决策卡、卡片生成、深潜提取、路径分析、对比打分
    mid  —— 中等长文：师资名单提取、实验室官网论文提取
    long —— 长文：论文精读（七段拆解）、M5 思考批改（需容纳论文全文）

用法：
    from llm_client import make_client, model_for
    client = make_client()
    client.chat.completions.create(model=model_for("long"), messages=[...])
"""
import sys
from pathlib import Path

# 项目根入 path：本模块是唯一为导入 config 而设置 sys.path 的地方
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import PROVIDER, API_KEY

PROVIDERS = {
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "fast": "moonshot-v1-8k",
        "mid": "moonshot-v1-32k",
        "long": "moonshot-v1-128k",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "fast": "deepseek-chat",
        "mid": "deepseek-chat",
        "long": "deepseek-chat",
    },
}

P = PROVIDERS[PROVIDER]

_client = None


def model_for(role: str = "fast") -> str:
    """取某个角色对应的模型名。未知角色直接报错，避免静默用错模型。"""
    if role not in ("fast", "mid", "long"):
        raise KeyError(f"未知模型角色 {role!r}，可用：fast / mid / long")
    return P[role]


def make_client():
    """OpenAI 客户端（进程内复用同一个实例，避免逐位老师/逐个任务重复建连）。"""
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=API_KEY, base_url=P["base_url"])
    return _client

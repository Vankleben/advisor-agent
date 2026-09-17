"""文本归一化：判断"引句是否真的在原文里"的唯一实现。

反幻觉校验（卡片 evidence、M3 精读、M5 批改与申诉、实验室官网论文、深潜证据）
做的事本质相同：两边文本归一化后比对，免疫 PDF 折行连字符、空白、中英标点差异。
此前这段逻辑在 6 个文件里各写一份，改一处漏五处。

用法：
    from text_norm import flat, loose
    if loose(quote) in loose(paper_text):
        ...  # 引句真实存在
"""
import re

_WS = re.compile(r"\s+")
_LOOSE = re.compile(r"[^0-9a-zA-Z一-鿿]+")


def flat(s) -> str:
    """白化：只去掉所有空白，保留标点。适合同一来源内的宽松比对。"""
    return _WS.sub("", str(s or ""))


def loose(s) -> str:
    """归一化：去掉空白与全部标点符号并小写，再做比对。
    可免疫 PDF 提取的折行连字符（Re-bound\\nForce）、全半角与中英标点差异。"""
    return _LOOSE.sub("", str(s or "")).lower()

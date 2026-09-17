"""网页抓取的公共层：统一 UA、超时、SSL 降级、编码修正与 HTML 清洗。

此前 6 个模块各写一套 requests.get、4 种不同 UA、6 套不同清洗逻辑，
导致同一个站点在不同工具里表现不一致。抓取一律走这里。

用法：
    from fetch_common import get, strip_html, clean
    r = get("https://example.com", timeout=20)      # 自动带 UA / SSL 降级 / 编码修正
    text = strip_html(r.text)                      # 正则去标签 → 单行正文
    page = clean(r.text, base=url, max_chars=8000)  # 结构化：标题 + 正文 + 链接列表
"""
import re
from html import unescape
from urllib.parse import urljoin

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 整块丢弃的标签（导航/页脚/脚本等噪音）
_BLOCK_TAGS = r"script|style|noscript|header|footer|nav|svg"
_BLOCK_RE = re.compile(rf"(?is)<({_BLOCK_TAGS}).*?</\1>")


def get(url: str, timeout: int = 20, headers: dict = None, params: dict = None,
        ssl_fallback: bool = True, check_status: bool = True) -> requests.Response:
    """GET 一个 URL：自动带 UA、修正编码、4xx/5xx 抛错；证书验证失败时降级重试一次。

    :param ssl_fallback: 证书过期/自签站点是否降级跳过验证（默认是）
    :param check_status: 是否对 4xx/5xx 抛 HTTPError（默认是；关掉则由调用方自己判 status）
    :raises requests.RequestException: 包含 SSL 降级、HTTP 错误在内的所有失败
    """
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)

    def _fix_encoding(resp: requests.Response) -> requests.Response:
        # 服务器没声明编码或声明了 ISO-8859-1（requests 的默认值）时按内容猜测，
        # 否则中文站点会乱码
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        if check_status:
            resp.raise_for_status()
        return resp

    try:
        return _fix_encoding(requests.get(url, headers=hdrs, params=params, timeout=timeout))
    except requests.exceptions.SSLError:
        if not ssl_fallback:
            raise
        print(f"⚠️ SSL 证书验证失败({url})，降级跳过验证")
        return _fix_encoding(requests.get(url, headers=hdrs, params=params,
                                         timeout=timeout, verify=False))


def strip_html(html: str) -> str:
    """去标签 → 单行纯文本（块级噪音标签整块丢弃）。用于正文提取与变化比对。"""
    text = _BLOCK_RE.sub(" ", html or "")
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def clean(html: str, base: str, max_chars: int, max_links: int = 80) -> dict:
    """把原始 HTML 清洗为 {title, text, links, error}。

    text 保留换行结构（供 Agent 阅读）；links 为去重后的可点击链接。
    给 fetch_url / render_url 共用。
    """
    title_match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = unescape(title_match.group(1).strip()) if title_match else ""
    html = _BLOCK_RE.sub(" ", html)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    links = []
    for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1).strip()
        link_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        link_text = unescape(link_text)[:60]
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        full_url = urljoin(base, href)
        if link_text and full_url.startswith("http"):
            links.append({"text": link_text, "url": full_url})
    seen, unique = set(), []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            unique.append(l)
    unique = unique[:max_links]

    text = re.sub(r"<[^>]+>", "\n", html)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[截断，原文共{}字符]".format(len(text))
    return {"title": title, "text": text, "links": unique, "error": ""}

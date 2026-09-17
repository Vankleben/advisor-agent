"""网页抓取的公共层：统一 UA、超时、SSL 降级、编码修正与 HTML 清洗。

此前 6 个模块各写一套 requests.get、4 种不同 UA、6 套不同清洗逻辑，
导致同一个站点在不同工具里表现不一致。抓取一律走这里。

三层传输，按顺序降级（调用方无需关心）：
  1) requests 直连；
  2) SSL 证书问题 → 跳过校验再试一次；
  3) TLS 指纹被拦（部分站点按客户端 TLS 指纹拒绝 Python，报 SSLEOFError）→ curl 兜底。
真正需要执行 JS 的页面再走 web_fetch.render_url（无头浏览器）。

用法：
    from fetch_common import get, strip_html, clean
    r = get("https://example.com", timeout=20)      # 自动带 UA / SSL 降级 / 编码修正
    text = strip_html(r.text)                      # 正则去标签 → 单行正文
    page = clean(r.text, base=url, max_chars=8000)  # 结构化：标题 + 正文 + 链接列表
"""
import os
import re
import shutil
import subprocess
import tempfile
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 整块丢弃的标签（导航/页脚/脚本等噪音）
_BLOCK_TAGS = r"script|style|noscript|header|footer|nav|svg"
_BLOCK_RE = re.compile(rf"(?is)<({_BLOCK_TAGS}).*?</\1>")

_CHARSET_RE = re.compile(rb'charset=["\']?\s*([\w-]+)', re.I)


class _CurlResponse:
    """curl 兜底传输的返回对象，提供调用方用到的那部分 requests.Response 接口。"""

    def __init__(self, url: str, status_code: int, content: bytes, encoding: str = ""):
        self.url = url
        self.status_code = status_code
        self.content = content
        self.encoding = encoding or self._guess_encoding(content)

    @staticmethod
    def _guess_encoding(content: bytes) -> str:
        m = _CHARSET_RE.search(content[:4096])
        if m:
            return m.group(1).decode("ascii", "ignore") or "utf-8"
        return "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    @property
    def apparent_encoding(self) -> str:
        return self.encoding

    def json(self):
        import json as _json
        return _json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _curl_exe() -> str:
    return shutil.which("curl") or shutil.which("curl.exe") or ""


def _get_via_curl(url: str, headers: dict = None, params: dict = None,
                  timeout: int = 20, insecure: bool = False):
    """用 curl 取页面（TLS 指纹被拦时的兜底）。curl 不存在或失败时返回 None。"""
    exe = _curl_exe()
    if not exe:
        return None
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    fd, tmp = tempfile.mkstemp(suffix=".body")
    os.close(fd)                      # Windows 下必须先关闭句柄，否则 curl 无法写入/删除
    try:
        cmd = [exe, "-sS", "-L", "--compressed", "-o", tmp,
               "-w", "%{http_code}", "--max-time", str(timeout)]
        if insecure:
            cmd.insert(1, "-k")
        for k, v in (headers or {}).items():
            cmd += ["-H", f"{k}: {v}"]
        cmd.append(url)
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 15,
                              encoding="utf-8", errors="replace")
        code = (proc.stdout or "").strip()
        if not code.isdigit():
            return None
        body = Path(tmp).read_bytes() if Path(tmp).exists() else b""
        return _CurlResponse(url, int(code), body)
    except Exception:
        return None
    finally:
        Path(tmp).unlink(missing_ok=True)


def get(url: str, timeout: int = 20, headers: dict = None, params: dict = None,
        ssl_fallback: bool = True, check_status: bool = True,
        transport: str = "auto") -> requests.Response:
    """GET 一个 URL：自动带 UA、修正编码、4xx/5xx 抛错；证书问题降级、TLS 指纹被拦时走 curl。

    :param ssl_fallback: 证书过期/自签站点是否降级跳过验证（默认是）
    :param check_status: 是否对 4xx/5xx 抛 HTTPError（默认是；关掉则由调用方自己判 status）
    :param transport: auto（默认，requests→SSL降级→curl）/ requests / curl
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

    if transport == "curl":
        resp = _get_via_curl(url, headers=hdrs, params=params, timeout=timeout)
        if resp is None:
            raise requests.ConnectionError(f"curl 兜底不可用或请求失败：{url}")
        return _fix_encoding(resp)

    try:
        return _fix_encoding(requests.get(url, headers=hdrs, params=params, timeout=timeout))
    except requests.exceptions.SSLError:
        # 先按"证书问题"降级；若降级仍失败（多为 TLS 指纹被 WAF 拦截，如 SSLEOFError），
        # 说明不是证书本身的问题，改用 curl 兜底（浏览器/curl 通常可正常访问）
        if ssl_fallback and transport == "auto":
            try:
                resp = _fix_encoding(requests.get(url, headers=hdrs, params=params,
                                                  timeout=timeout, verify=False))
                print(f"⚠️ SSL 证书验证失败({url})，已降级跳过验证")
                return resp
            except requests.exceptions.SSLError:
                pass
        if transport == "auto":
            resp = _get_via_curl(url, headers=hdrs, params=params, timeout=timeout)
            if resp is not None:
                print(f"ℹ️ requests 被 TLS 层拒绝({url})，已用 curl 兜底取回 "
                      f"HTTP {resp.status_code}")
                return _fix_encoding(resp)
        raise


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

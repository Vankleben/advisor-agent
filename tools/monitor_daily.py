"""
M6 每日自动监测：定时任务入口（Windows 计划任务 / 手动 daily）
用法：
  python tools/monitor_daily.py            # 跑一次，有变化才输出简报
  python tools/monitor.py scan            # 同 scan，但带真实变化才落盘简报

行为：调 monitor.scan() 扫全部收藏老师；若存在真实新增（主页源新增/新论文/新仓库），
把简报写入 data/monitor/今日简报.txt 并打印；否则打印"今日无变化"。
适合配 Windows 任务计划每天自动执行，有变化时主动留痕。
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import sys
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

import monitor as mon


def main() -> None:
    briefing = mon.scan()
    if briefing.get("error"):
        print(briefing["error"])
        return

    # 是否有真实新增：判定逻辑与 monitor.scan 的 summary 共用同一函数，避免两处判定漂移
    real, real_name = mon.has_real_changes(briefing)

    today = datetime.date.today().isoformat()
    out = Path(BASE_DIR / "data" / "monitor" / f"每日简报_{today}.txt")
    if real:
        lines = [f"# 情报简报 {today}"]
        for t in briefing["per_teacher"]:
            if t["changes"] or t["arxiv"] or t["github"]:
                lines.append(f"\n## {t['name']}")
                lines += [f"- {c}" for c in t["changes"]]
                lines += [f"- [arXiv] {a}" for a in t["arxiv"]]
                lines += [f"- [GitHub] {g}" for g in t["github"]]
        text = "\n".join(lines)
        out.write_text(text, encoding="utf-8")
        print(f"[M6] {real_name} 位老师有新增动态，简报已存：{out}")
    else:
        print(f"[M6] {today} 今日无实质变化")


if __name__ == "__main__":
    sys.exit(main())
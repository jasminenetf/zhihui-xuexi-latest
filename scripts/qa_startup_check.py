#!/usr/bin/env python3
"""One-click startup acceptance probe. Does not print secrets."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:8010"
FRONTEND = "http://127.0.0.1:5173"


def _get(url: str, timeout: int = 5) -> tuple[bool, int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read(5000).decode("utf-8", errors="replace")
            return True, resp.status, text
    except urllib.error.HTTPError as exc:
        return False, exc.code, exc.read(500).decode("utf-8", errors="replace")
    except Exception as exc:
        return False, None, str(exc)


def main() -> int:
    print("=== Startup QA Check ===")
    bat = ROOT / "启动智能学习Agent.bat"
    print(f"启动脚本: {'OK' if bat.exists() else 'MISSING'} {bat.name}")

    ok, status, body = _get(BACKEND + "/health")
    print(f"后端健康检查: {'OK' if ok and status == 200 else 'FAIL'} status={status}")
    if ok:
        try:
            parsed = json.loads(body)
            print(f"后端模式: {parsed.get('mode') or parsed.get('status') or 'unknown'}")
        except Exception:
            pass

    ok_boot, boot_status, boot_body = _get(BACKEND + "/api/app/bootstrap", timeout=8)
    print(f"后端 bootstrap: {'OK' if ok_boot and boot_status == 200 else 'FAIL'} status={boot_status}")
    if ok_boot:
        print("bootstrap 关键字段: " + ("OK" if all(x in boot_body for x in ["courses", "config"]) else "CHECK"))

    ok_front, front_status, front_body = _get(FRONTEND + "/", timeout=5)
    print(f"前端访问: {'OK' if ok_front and front_status == 200 else 'FAIL'} status={front_status}")
    if ok_front:
        needed = ["智学工坊", "学习工作台", "chat-input"]
        print("前端关键 DOM: " + ("OK" if all(x in front_body for x in needed) else "CHECK"))

    if not (bat.exists() and ok and status == 200 and ok_boot and boot_status == 200 and ok_front and front_status == 200):
        print("\n手动验收步骤：")
        print("1. 双击 启动智能学习Agent.bat")
        print("2. 打开 http://127.0.0.1:5173")
        print("3. 确认首页显示学习工作台，右上角可进入直接提问")
        print("4. 访问 http://127.0.0.1:8010/health 应返回 ok=true")
        return 1

    print("\n=== STARTUP QA PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

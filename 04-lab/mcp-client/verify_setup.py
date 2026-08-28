#!/usr/bin/env python3
"""Kiểm tra setup của Weather Agent trước khi chạy `adk web`.

Chạy: uv run python verify_setup.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Console Windows mặc định dùng cp1252, không in được tiếng Việt và sẽ ném
# UnicodeEncodeError ngay khi khởi động. Ép UTF-8 cho stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")


def check_environment() -> bool:
    """Kiểm tra .env và API key. Chấp nhận .env ở gốc repo hoặc trong thư mục này."""
    print("[1/5] Cấu hình môi trường")

    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        print("  FAIL: chưa cài python-dotenv. Chạy: uv sync")
        return False

    env_path = find_dotenv(usecwd=False)
    if not env_path:
        print("  FAIL: không tìm thấy file .env nào từ thư mục này trở lên")
        print('  Sửa: Set-Content -Path "..\\..\\.env" -Value "GEMINI_API_KEY=<key>" -Encoding ascii')
        return False

    load_dotenv(env_path)
    print(f"  OK: đọc .env tại {env_path}")

    # google-genai đọc GOOGLE_API_KEY; tài liệu Gemini hay dùng GEMINI_API_KEY.
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key or api_key.startswith("your_"):
        print("  FAIL: thiếu GOOGLE_API_KEY (hoặc GEMINI_API_KEY)")
        print("  Lấy key tại https://aistudio.google.com/apikey")
        return False
    print(f"  OK: Gemini key đã đặt ({api_key[:6]}...{api_key[-4:]})")

    # Server đọc key này. Thiếu thì agent vẫn chat được nhưng tool trả lỗi.
    if not os.getenv("WEATHERAPI_KEY"):
        print("  WARN: thiếu WEATHERAPI_KEY — server sẽ trả lỗi có cấu trúc thay vì dữ liệu")
        print("  Lấy key free tại https://www.weatherapi.com/")
    else:
        print("  OK: WEATHERAPI_KEY đã đặt")

    return True


def check_dependencies() -> bool:
    print("\n[2/5] Thư viện")
    packages = [
        ("google.adk", "google-adk"),
        ("mcp", "mcp"),
        ("dotenv", "python-dotenv"),
        ("httpx", "httpx"),
    ]

    ok = True
    for module, name in packages:
        try:
            __import__(module)
            print(f"  OK: {name}")
        except ImportError:
            print(f"  FAIL: thiếu {name}")
            ok = False

    if not ok:
        print("  Sửa: uv sync")
    return ok


def check_agent_structure() -> bool:
    print("\n[3/5] Cấu trúc agent")
    ok = True
    for rel in ("weather_agent/agent.py", "weather_agent/__init__.py"):
        if Path(rel).exists():
            print(f"  OK: {rel}")
        else:
            print(f"  FAIL: thiếu {rel}")
            ok = False
    return ok


def check_mcp_server() -> bool:
    """Bắt tay MCP thật với server, không chỉ ping HTTP.

    Bản cũ chỉ GET một URL Cloud Run hardcode và coi 404 là thành công — điều đó
    không chứng minh được server nói đúng giao thức MCP.
    """
    print(f"\n[4/5] MCP server tại {MCP_SERVER_URL}")

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        print("  FAIL: thiếu mcp SDK. Chạy: uv sync")
        return False

    async def handshake():
        async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                resources = await session.list_resources()
                return init, tools.tools, resources.resources

    try:
        init, tools, resources = asyncio.run(asyncio.wait_for(handshake(), timeout=20))
    except asyncio.TimeoutError:
        print("  FAIL: server không phản hồi trong 20 giây")
        print("  Sửa: cd ../mcp-server && uv run python weather.py")
        return False
    except Exception as exc:
        print(f"  FAIL: không bắt tay được — {type(exc).__name__}: {exc}")
        print("  Sửa: cd ../mcp-server && uv run python weather.py")
        return False

    print(f"  OK: {init.serverInfo.name} v{init.serverInfo.version}")
    print(f"  OK: {len(tools)} tool — {', '.join(t.name for t in tools)}")
    print(f"  OK: {len(resources)} resource — {', '.join(str(r.uri) for r in resources)}")
    return True


def check_agent_import() -> bool:
    print("\n[5/5] Import agent")
    try:
        import warnings

        warnings.filterwarnings("ignore")
        from weather_agent import root_agent

        tool_count = len(root_agent.tools) if root_agent.tools else 0
        print(f"  OK: {root_agent.name} · model {root_agent.model}")
        if tool_count == 0:
            print("  WARN: agent đang ở chế độ fallback, chưa gắn được MCP toolset")
        return True
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("=" * 60)
    print("Weather Agent — kiểm tra setup")
    print("=" * 60 + "\n")

    # Chạy tuần tự và giữ đủ kết quả: một bước hỏng không nên che các bước sau.
    results = [
        check_environment(),
        check_dependencies(),
        check_agent_structure(),
        check_mcp_server(),
        check_agent_import(),
    ]

    print("\n" + "=" * 60)
    if all(results):
        print("Tất cả kiểm tra đạt. Chạy: uv run adk web")
        print("Rồi mở http://localhost:8000 và chọn weather_agent")
        return 0

    print(f"{results.count(False)}/{len(results)} kiểm tra hỏng — xem chi tiết ở trên")
    return 1


if __name__ == "__main__":
    sys.exit(main())

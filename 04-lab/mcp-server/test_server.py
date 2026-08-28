#!/usr/bin/env python3
"""Smoke test cho Weather MCP Server — bản chạy được bằng lệnh của MCP Inspector.

Inspector là công cụ tương tác trong trình duyệt; script này kiểm cùng những thứ đó
nhưng chạy headless nên đưa được vào CI. Nó verify:
  1. Bắt tay MCP và capability negotiation
  2. Schema của tool (tên, mô tả, tham số bắt buộc)
  3. Resource và prompt được công bố
  4. Đường thành công của tool
  5. Đường LỖI — phần hay bị bỏ sót nhất khi test thủ công

Chạy:
    uv run python weather.py            # terminal 1
    uv run python test_server.py        # terminal 2
"""

import asyncio
import json
import os
import sys

from dotenv import find_dotenv, load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv(find_dotenv(usecwd=False))

# Console Windows mặc định dùng cp1252, không in được tiếng Việt và sẽ ném
# UnicodeEncodeError ngay khi khởi động. Ép UTF-8 cho stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
    return condition


def text_of(result) -> str:
    """Gộp phần text trong kết quả call_tool."""
    return "\n".join(block.text for block in result.content if block.type == "text")


def as_error(payload: str) -> dict | None:
    """Trả dict lỗi nếu payload là structured error, None nếu không phải."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    return data.get("error") if isinstance(data, dict) and data.get("ok") is False else None


async def main() -> int:
    print(f"Kết nối {SERVER_URL}\n")

    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:

            # -- 1. Handshake ------------------------------------------------
            print("[1] Bắt tay và capability negotiation")
            init = await session.initialize()
            # Lưu ý: FastMCP 1.x điền serverInfo.version bằng version của MCP SDK,
            # không phải version của server. Version thật nằm ở resource server://info.
            check("server tự khai báo danh tính", init.serverInfo.name == "weather",
                  f"name={init.serverInfo.name}, sdk={init.serverInfo.version}")
            caps = init.capabilities
            check("công bố capability tools", caps.tools is not None)
            check("công bố capability resources", caps.resources is not None)
            check("công bố capability prompts", caps.prompts is not None)

            # -- 2. Tool schema ----------------------------------------------
            print("\n[2] Schema tool (LLM chọn tool 100% dựa vào name + description)")
            tools = {t.name: t for t in (await session.list_tools()).tools}
            check("đủ 3 tool", len(tools) == 3, ", ".join(sorted(tools)))

            for name in ("get_current_weather", "get_forecast", "health_check"):
                check(f"tool {name} tồn tại", name in tools)

            if "get_current_weather" in tools:
                tool = tools["get_current_weather"]
                schema = tool.inputSchema
                check("get_current_weather bắt buộc có 'city'",
                      schema.get("required") == ["city"])
                check("get_current_weather có description đủ dài",
                      len(tool.description or "") > 80,
                      f"{len(tool.description or '')} ký tự")
                check("description nêu rõ khi nào KHÔNG dùng",
                      "Do NOT use" in (tool.description or ""))

            if "get_forecast" in tools:
                props = tools["get_forecast"].inputSchema.get("properties", {})
                check("get_forecast có tham số optional 'days'",
                      "days" in props and "days" not in tools["get_forecast"].inputSchema.get("required", []),
                      "client cũ gọi không truyền days vẫn chạy")

            # -- 3. Resources và prompts --------------------------------------
            print("\n[3] Resources và prompts")
            resources = {str(r.uri) for r in (await session.list_resources()).resources}
            for uri in ("weather://schema", "weather://cities", "server://info"):
                check(f"resource {uri}", uri in resources)

            if "weather://schema" in resources:
                content = await session.read_resource("weather://schema")
                body = json.loads(content.contents[0].text)
                check("weather://schema mô tả error envelope", "error_envelope" in body)

            if "server://info" in resources:
                content = await session.read_resource("server://info")
                info = json.loads(content.contents[0].text)
                check("server://info công bố version thật của server",
                      info.get("version") == "2.0.0", f"v{info.get('version')}")
                check("server://info công bố giới hạn forecast",
                      info.get("limits", {}).get("forecast_days_max") == 3)

            prompts = {p.name for p in (await session.list_prompts()).prompts}
            check("có prompt template", len(prompts) >= 2, ", ".join(sorted(prompts)))

            # -- 4. Đường thành công ------------------------------------------
            print("\n[4] Gọi tool — đường thành công")
            health_raw = text_of(await session.call_tool("health_check", {}))
            health = json.loads(health_raw)
            check("health_check trả JSON hợp lệ", health.get("ok") is True)

            # Kiểm đúng thứ cần kiểm: giá trị key thật không được lọt ra ngoài.
            # Tìm chữ "key" trong output là sai — mọi thông báo nhắc tên biến
            # WEATHERAPI_KEY đều dính, dù chẳng lộ gì.
            secret = os.getenv("WEATHERAPI_KEY")
            check("health_check không lộ giá trị API key",
                  not secret or secret not in health_raw,
                  "chỉ báo đã cấu hình hay chưa, không trả giá trị")

            has_key = health.get("api_key_configured", False)
            if has_key:
                current = text_of(await session.call_tool("get_current_weather", {"city": "Hanoi"}))
                check("get_current_weather('Hanoi') trả dữ liệu thật",
                      as_error(current) is None and "°C" in current)

                forecast = text_of(await session.call_tool("get_forecast", {"city": "Da Nang", "days": 2}))
                check("get_forecast('Da Nang', 2) trả dữ liệu thật",
                      as_error(forecast) is None and "Dự báo" in forecast)

                capped = text_of(await session.call_tool("get_forecast", {"city": "Hue", "days": 10}))
                check("days=10 bị cắt về 3 thay vì lỗi",
                      as_error(capped) is None and "Đã cắt" in capped)
            else:
                print("  SKIP  gọi API thật — thiếu WEATHERAPI_KEY")

            # -- 5. Đường lỗi -------------------------------------------------
            print("\n[5] Gọi tool — đường lỗi (structured, không phải exception)")

            empty = text_of(await session.call_tool("get_current_weather", {"city": "   "}))
            err = as_error(empty)
            check("city rỗng trả structured error", err is not None)
            check("lỗi city rỗng có code đúng", err and err.get("code") == "missing_city")
            check("lỗi city rỗng đánh dấu không retry được", err and err.get("retryable") is False)

            bad_days = text_of(await session.call_tool("get_forecast", {"city": "Hanoi", "days": 0}))
            err = as_error(bad_days)
            check("days=0 trả structured error", err is not None)
            check("lỗi days có code invalid_days", err and err.get("code") == "invalid_days")

            if has_key:
                nowhere = text_of(await session.call_tool("get_current_weather",
                                                          {"city": "Xyzzyville Nonexistent"}))
                err = as_error(nowhere)
                check("thành phố không tồn tại trả structured error", err is not None)
                check("lỗi có hint để người dùng tự sửa", err and bool(err.get("hint")))
            else:
                nokey = text_of(await session.call_tool("get_current_weather", {"city": "Hanoi"}))
                err = as_error(nokey)
                check("thiếu key trả structured error thay vì crash", err is not None)
                check("lỗi thiếu key có code missing_api_key",
                      err and err.get("code") == "missing_api_key")

    print("\n" + "=" * 56)
    print(f"{passed} đạt · {failed} hỏng")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print(f"\nKhông chạy được test: {type(exc).__name__}: {exc}")
        print(f"Server đã chạy chưa? uv run python weather.py")
        sys.exit(2)

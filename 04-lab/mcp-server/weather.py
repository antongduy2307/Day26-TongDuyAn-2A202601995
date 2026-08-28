"""Weather MCP Server — FastMCP + WeatherAPI.com.

Expose 3 tools, 3 resources và 2 prompts qua Streamable HTTP (mặc định) hoặc stdio.

Thiết kế theo bài giảng Ngày 26:
  - Tool description là thứ LLM dựa vào để chọn tool → mô tả nêu rõ "dùng khi nào".
  - Lỗi trả về dưới dạng structured JSON, không raise exception, để client retry/fallback.
  - Resources cung cấp context tĩnh (schema, danh mục) thay vì nhồi vào system prompt.
  - Output giữ gọn; payload thô để trong resource, không dump vào mỗi lần gọi tool.
"""

from typing import Any
import json
import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv
from mcp.server.fastmcp import FastMCP

# Console Windows mặc định dùng cp1252, không in được tiếng Việt và sẽ ném
# UnicodeEncodeError ngay khi khởi động. Ép UTF-8 cho stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Đọc .env gần nhất tính từ file này trở lên — cho phép dùng chung 1 .env ở gốc repo.
load_dotenv(find_dotenv(usecwd=False))

SERVER_NAME = "weather"
SERVER_VERSION = "2.0.0"

WEATHERAPI_BASE = "https://api.weatherapi.com/v1"
USER_AGENT = f"weather-mcp-server/{SERVER_VERSION}"

# Giới hạn của WeatherAPI free tier.
MAX_FORECAST_DAYS = 3

port = int(os.getenv("PORT", 8085))
mcp = FastMCP(SERVER_NAME, host="0.0.0.0", port=port)


# --------------------------------------------------------------------------
# Structured errors
# --------------------------------------------------------------------------
# Tool KHÔNG raise exception. Một exception ném qua ranh giới MCP chỉ còn lại
# stack trace vô nghĩa với LLM. Thay vào đó trả JSON có `code` để client phân
# biệt lỗi tạm thời (retry được) với lỗi cấu hình (retry vô ích).

# Mã lỗi WeatherAPI → (code nội bộ, có nên retry không, gợi ý xử lý)
_UPSTREAM_ERRORS: dict[int, tuple[str, bool, str]] = {
    1002: ("missing_api_key", False, "Đặt WEATHERAPI_KEY trong .env rồi khởi động lại server."),
    1003: ("missing_city", False, "Truyền tham số 'city' không rỗng."),
    1005: ("bad_request", False, "Lỗi nội bộ của server, không phải lỗi người dùng."),
    1006: ("city_not_found", False, "Kiểm tra chính tả, hoặc thử tên tiếng Anh (Hanoi thay vì Hà Nội)."),
    2006: ("invalid_api_key", False, "WEATHERAPI_KEY sai. Lấy key mới tại weatherapi.com."),
    2007: ("quota_exceeded", False, "Hết hạn mức tháng của WeatherAPI free tier."),
    2008: ("api_key_disabled", False, "Key đã bị vô hiệu hoá tại weatherapi.com."),
    2009: ("plan_not_allowed", False, "Gói hiện tại không cho phép endpoint này."),
}


def _error(code: str, message: str, *, retryable: bool, hint: str = "") -> str:
    """Đóng gói lỗi thành JSON để LLM đọc được và quyết định fallback."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": retryable},
    }
    if hint:
        payload["error"]["hint"] = hint
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _request(endpoint: str, params: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    """Gọi WeatherAPI. Trả (data, None) khi thành công, (None, json_lỗi) khi hỏng.

    Không nuốt lỗi thành None trần như bản cũ — mất nguyên nhân thật thì client
    không thể phân biệt "sai tên thành phố" với "hết quota".
    """
    api_key = os.getenv("WEATHERAPI_KEY")
    if not api_key:
        return None, _error(
            "missing_api_key",
            "Server chưa được cấu hình WEATHERAPI_KEY.",
            retryable=False,
            hint="Thêm WEATHERAPI_KEY=... vào .env rồi khởi động lại server.",
        )

    url = f"{WEATHERAPI_BASE}/{endpoint}"
    request_params = {**params, "key": api_key}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"User-Agent": USER_AGENT}, params=request_params, timeout=30.0
            )
            response.raise_for_status()
            return response.json(), None

    except httpx.HTTPStatusError as exc:
        # WeatherAPI trả lỗi nghiệp vụ trong body JSON kèm mã riêng.
        upstream_code = None
        upstream_message = exc.response.text
        try:
            body = exc.response.json()
            upstream_code = body.get("error", {}).get("code")
            upstream_message = body.get("error", {}).get("message", upstream_message)
        except ValueError:
            pass

        if upstream_code in _UPSTREAM_ERRORS:
            code, retryable, hint = _UPSTREAM_ERRORS[upstream_code]
            return None, _error(code, upstream_message, retryable=retryable, hint=hint)

        # 5xx của WeatherAPI là lỗi tạm thời — client nên thử lại.
        retryable = exc.response.status_code >= 500
        return None, _error(
            "upstream_http_error",
            f"WeatherAPI trả HTTP {exc.response.status_code}: {upstream_message}",
            retryable=retryable,
        )

    except httpx.TimeoutException:
        return None, _error(
            "upstream_timeout", "WeatherAPI không phản hồi trong 30 giây.", retryable=True
        )

    except httpx.RequestError as exc:
        return None, _error(
            "network_error", f"Không kết nối được WeatherAPI: {exc}", retryable=True
        )


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@mcp.tool()
async def get_current_weather(city: str) -> str:
    """Lấy điều kiện thời tiết HIỆN TẠI của một thành phố.

    Use this when: người dùng hỏi thời tiết ngay lúc này, nhiệt độ đang bao nhiêu,
    trời có mưa không, có nên mang ô không.
    Do NOT use this for: dự báo ngày mai hoặc các ngày tới — dùng get_forecast.

    Args:
        city: Tên thành phố, ưu tiên tiếng Anh không dấu (ví dụ "Hanoi",
            "Da Nang", "Ho Chi Minh City", "Tokyo"). Cũng chấp nhận
            "lat,lon" (ví dụ "21.03,105.85") hoặc mã sân bay IATA.

    Returns:
        Tóm tắt thời tiết dạng text khi thành công; JSON có khoá "error" khi thất bại.
    """
    if not city or not city.strip():
        return _error("missing_city", "Tham số 'city' rỗng.", retryable=False)

    data, error = await _request("current.json", {"q": city.strip(), "aqi": "no"})
    if error:
        return error

    current = data["current"]
    location = data["location"]

    return (
        f"Thời tiết hiện tại — {location['name']}, {location['region']}, {location['country']}\n"
        f"Nhiệt độ: {current['temp_c']}°C (cảm giác {current['feelslike_c']}°C)\n"
        f"Trạng thái: {current['condition']['text']}\n"
        f"Độ ẩm: {current['humidity']}%\n"
        f"Gió: {current['wind_kph']} km/h hướng {current['wind_dir']}\n"
        f"Áp suất: {current['pressure_mb']} mb\n"
        f"Chỉ số UV: {current['uv']}\n"
        f"Tầm nhìn: {current['vis_km']} km\n"
        f"Cập nhật lúc: {current['last_updated']} (giờ địa phương)"
    )


@mcp.tool()
async def get_forecast(city: str, days: int = 3) -> str:
    """Lấy DỰ BÁO thời tiết nhiều ngày cho một thành phố.

    Use this when: người dùng hỏi thời tiết ngày mai, cuối tuần, vài ngày tới,
    hoặc muốn lên kế hoạch đi lại.
    Do NOT use this for: thời tiết ngay lúc này — dùng get_current_weather.

    Args:
        city: Tên thành phố, ưu tiên tiếng Anh không dấu (ví dụ "Hanoi", "Tokyo").
        days: Số ngày dự báo, 1 đến 3. Giá trị lớn hơn 3 sẽ bị cắt về 3 vì
            WeatherAPI free tier chỉ cho tối đa 3 ngày. Ngày đầu tiên là hôm nay.

    Returns:
        Dự báo theo ngày dạng text khi thành công; JSON có khoá "error" khi thất bại.
    """
    if not city or not city.strip():
        return _error("missing_city", "Tham số 'city' rỗng.", retryable=False)

    if days < 1:
        return _error(
            "invalid_days", f"days={days} không hợp lệ, phải từ 1 đến {MAX_FORECAST_DAYS}.",
            retryable=False,
        )

    capped = min(days, MAX_FORECAST_DAYS)
    data, error = await _request(
        "forecast.json", {"q": city.strip(), "days": str(capped), "aqi": "no", "alerts": "no"}
    )
    if error:
        return error

    location = data["location"]
    lines = [
        f"Dự báo {capped} ngày — {location['name']}, {location['region']}, {location['country']}"
    ]
    if capped < days:
        lines.append(f"(Đã cắt từ {days} xuống {capped} ngày — giới hạn của free tier.)")

    for entry in data["forecast"]["forecastday"]:
        day = entry["day"]
        lines.append(
            f"\n{entry['date']}\n"
            f"  Cao nhất: {day['maxtemp_c']}°C · Thấp nhất: {day['mintemp_c']}°C\n"
            f"  Trạng thái: {day['condition']['text']}\n"
            f"  Khả năng mưa: {day['daily_chance_of_rain']}%\n"
            f"  Gió mạnh nhất: {day['maxwind_kph']} km/h · UV: {day['uv']}"
        )

    return "\n".join(lines)


@mcp.tool()
async def health_check() -> str:
    """Kiểm tra server còn sống và đã cấu hình đủ chưa.

    Use this when: cần xác minh server sau khi deploy, hoặc chẩn đoán khi các
    tool thời tiết báo lỗi mà chưa rõ do server hay do mạng.

    Returns:
        JSON gồm trạng thái server, phiên bản, và việc API key đã được cấu hình chưa.
        Không bao giờ trả về giá trị của key.
    """
    configured = bool(os.getenv("WEATHERAPI_KEY"))
    return json.dumps(
        {
            "ok": True,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "upstream": "weatherapi.com",
            "api_key_configured": configured,
            "status": "ready" if configured else "degraded",
            "detail": (
                "Server sẵn sàng phục vụ."
                if configured
                else "Server chạy nhưng thiếu WEATHERAPI_KEY — các tool thời tiết sẽ trả lỗi."
            ),
            "tools": ["get_current_weather", "get_forecast", "health_check"],
        },
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------
# Resources — dynamic context injection
# --------------------------------------------------------------------------
# Slide 6 và 26 của bài giảng: Resources bị dùng thiếu. Chúng là chỗ để đặt
# context tĩnh (schema, danh mục, metadata) mà host đọc khi cần, thay vì
# hardcode vào system prompt hay nhồi vào mỗi kết quả tool.

@mcp.resource("weather://schema")
def weather_schema() -> str:
    """Schema các trường dữ liệu mà tool thời tiết trả về, kèm đơn vị đo."""
    return json.dumps(
        {
            "current_weather": {
                "temp_c": {"type": "number", "unit": "°C"},
                "feelslike_c": {"type": "number", "unit": "°C"},
                "condition": {"type": "string", "example": "Patchy rain nearby"},
                "humidity": {"type": "integer", "unit": "%"},
                "wind_kph": {"type": "number", "unit": "km/h"},
                "wind_dir": {"type": "string", "example": "NNE"},
                "pressure_mb": {"type": "number", "unit": "millibar"},
                "uv": {"type": "number", "scale": "0-11+, trên 8 là rất cao"},
                "vis_km": {"type": "number", "unit": "km"},
            },
            "forecast_day": {
                "date": {"type": "string", "format": "YYYY-MM-DD"},
                "maxtemp_c": {"type": "number", "unit": "°C"},
                "mintemp_c": {"type": "number", "unit": "°C"},
                "daily_chance_of_rain": {"type": "integer", "unit": "%"},
                "maxwind_kph": {"type": "number", "unit": "km/h"},
            },
            "error_envelope": {
                "ok": {"type": "boolean", "value": False},
                "error.code": {"type": "string", "example": "city_not_found"},
                "error.message": {"type": "string"},
                "error.retryable": {"type": "boolean", "note": "True thì client nên thử lại"},
                "error.hint": {"type": "string", "note": "Gợi ý cách khắc phục, có thể vắng"},
            },
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("weather://cities")
def reference_cities() -> str:
    """Danh mục thành phố tham chiếu — giúp LLM chuẩn hoá tên tiếng Việt sang tên API nhận."""
    return json.dumps(
        {
            "note": "WeatherAPI nhận tên tiếng Anh không dấu. Dùng bảng này để chuẩn hoá.",
            "vietnam": {
                "Hà Nội": "Hanoi",
                "Hải Phòng": "Haiphong",
                "Đà Nẵng": "Da Nang",
                "Huế": "Hue",
                "Nha Trang": "Nha Trang",
                "Đà Lạt": "Da Lat",
                "TP Hồ Chí Minh": "Ho Chi Minh City",
                "Cần Thơ": "Can Tho",
            },
            "fallback": "Không có trong bảng thì truyền thẳng tên tiếng Anh, hoặc 'lat,lon'.",
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("server://info")
def server_info() -> str:
    """Metadata của server — version, giới hạn, transport. Client đọc để biết khả năng server."""
    return json.dumps(
        {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol": "MCP over JSON-RPC 2.0",
            "transports": {
                "streamable-http": f"http://localhost:{port}/mcp — mặc định, dùng cho remote",
                "stdio": "python weather.py --stdio — dùng cho Claude Desktop / Inspector local",
            },
            "limits": {
                "forecast_days_max": MAX_FORECAST_DAYS,
                "upstream_timeout_seconds": 30,
                "note": "Giới hạn đến từ WeatherAPI free tier, không phải từ server.",
            },
            "deprecated_tools": [],
            "auth": "Không có. Chỉ chạy localhost. Expose ra internet thì bắt buộc thêm auth.",
        },
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------
# Prompts — reusable templates
# --------------------------------------------------------------------------

@mcp.prompt()
def travel_advice(city: str, days: int = 3) -> str:
    """Template hỏi tư vấn chuẩn bị cho chuyến đi dựa trên dự báo thời tiết."""
    return (
        f"Dùng get_forecast cho {city} trong {days} ngày tới, rồi tư vấn:\n"
        f"1. Nên mang loại quần áo gì\n"
        f"2. Có cần mang ô hoặc áo mưa không\n"
        f"3. Ngày nào trong khoảng đó thích hợp nhất cho hoạt động ngoài trời\n"
        f"Trả lời ngắn gọn, nêu rõ căn cứ là con số nào trong dự báo."
    )


@mcp.prompt()
def compare_cities(city_a: str, city_b: str) -> str:
    """Template so sánh thời tiết hiện tại giữa hai thành phố."""
    return (
        f"Gọi get_current_weather cho cả {city_a} và {city_b}, rồi so sánh nhiệt độ, "
        f"độ ẩm và điều kiện thời tiết. Kết luận nơi nào dễ chịu hơn ngay lúc này và vì sao."
    )


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------

if __name__ == "__main__":
    # stdio khi được host spawn (Claude Desktop, MCP Inspector), streamable-http
    # khi chạy như dịch vụ. Chọn tường minh bằng cờ thay vì đoán qua isatty() —
    # bản cũ đoán sai khi chạy trong terminal có pipe.
    use_stdio = "--stdio" in sys.argv

    if use_stdio:
        print(f"[{SERVER_NAME} v{SERVER_VERSION}] stdio transport", file=sys.stderr)
        mcp.run(transport="stdio")
    else:
        print(f"[{SERVER_NAME} v{SERVER_VERSION}] streamable-http tại http://0.0.0.0:{port}/mcp")
        print("Tools: get_current_weather, get_forecast, health_check")
        print("Resources: weather://schema, weather://cities, server://info")
        print("Prompts: travel_advice, compare_cities")
        if not os.getenv("WEATHERAPI_KEY"):
            print("CẢNH BÁO: thiếu WEATHERAPI_KEY — tool thời tiết sẽ trả lỗi có cấu trúc.")
        mcp.run(transport="streamable-http")

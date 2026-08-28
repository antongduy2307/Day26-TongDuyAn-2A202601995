"""Weather Agent — Google ADK đóng vai MCP Client.

ADK làm 5 việc trong lab này:
  1. Kết nối MCP server qua Streamable HTTP (StreamableHTTPConnectionParams)
  2. Khám phá tool tự động lúc runtime (McpToolset gọi tools/list)
  3. Truyền tool schema cho Gemini
  4. Điều phối vòng lặp function calling: model chọn tool → gọi server → đưa kết quả về model
  5. Cung cấp web UI qua `adk web`
"""

import logging
import os

from dotenv import find_dotenv, load_dotenv
from google.adk import Agent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Đọc .env gần nhất đi ngược lên cây thư mục — cho phép dùng chung 1 .env ở gốc repo
# thay vì phải copy key vào từng thư mục con.
load_dotenv(find_dotenv(usecwd=False))

# google-genai đọc GOOGLE_API_KEY. Nhiều tài liệu Gemini lại hướng dẫn đặt
# GEMINI_API_KEY, nên chấp nhận cả hai và tự ánh xạ sang tên mà SDK cần.
if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

if not os.getenv("GOOGLE_API_KEY"):
    logger.warning(
        "Chưa có GOOGLE_API_KEY (hoặc GEMINI_API_KEY). Agent sẽ khởi tạo được "
        "nhưng mọi lượt chat sẽ lỗi xác thực. Lấy key tại https://aistudio.google.com/apikey"
    )

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8085/mcp")
MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

# Instruction front-load ý chính (bài giảng Ngày 26, phần best practices):
# nói rõ khi nào cần tool nào, và cấm bịa số liệu khi tool lỗi.
INSTRUCTION = """Bạn là trợ lý thời tiết. Mọi số liệu thời tiết PHẢI lấy từ tool, tuyệt đối không tự bịa.

Chọn tool:
- Thời tiết ngay lúc này → get_current_weather(city)
- Ngày mai / vài ngày tới / lên kế hoạch → get_forecast(city, days) với days từ 1 đến 3
- Nghi server hỏng, hoặc tool báo lỗi lạ → health_check()

Chuẩn hoá tên thành phố sang tiếng Anh không dấu trước khi gọi tool: "Hà Nội" → "Hanoi",
"Đà Nẵng" → "Da Nang", "TP.HCM" → "Ho Chi Minh City". Nếu không chắc, đọc resource
weather://cities.

Khi tool trả JSON có "ok": false — đó là lỗi có cấu trúc, không phải dữ liệu thời tiết:
- error.retryable = true → thử lại đúng một lần, vẫn hỏng thì báo người dùng
- error.retryable = false → báo ngay, nêu lại error.hint bằng lời dễ hiểu
Không bao giờ suy đoán thời tiết thay cho kết quả tool bị lỗi.

Người dùng hỏi nhiều thành phố thì gọi tool nhiều lần rồi tổng hợp. Trả lời bằng ngôn ngữ
người dùng đang dùng, ngắn gọn, nêu đơn vị đo kèm số."""

logger.info("Weather agent → MCP server: %s", MCP_SERVER_URL)

try:
    connection_params = StreamableHTTPConnectionParams(
        url=MCP_SERVER_URL,
        timeout=30.0,
    )

    # McpToolset tự gọi tools/list lúc runtime — agent không hardcode tool nào.
    # Thêm tool ở server thì client này nhận được mà không phải sửa dòng code nào.
    weather_tools = McpToolset(connection_params=connection_params)

    root_agent = Agent(
        name="weather_agent",
        model=MODEL,
        instruction=INSTRUCTION,
        tools=[weather_tools],
    )
    logger.info("Đã gắn MCP toolset. Tool được khám phá lúc chạy, không hardcode.")

except Exception as exc:
    logger.error("Không tạo được MCP toolset (%s): %s", MCP_SERVER_URL, exc, exc_info=True)
    logger.warning(
        "Chạy fallback KHÔNG có tool. Khởi động server trước "
        "(cd 04-lab/mcp-server && uv run python weather.py) rồi chạy lại adk web."
    )

    root_agent = Agent(
        name="weather_agent",
        model=MODEL,
        instruction=(
            "Bạn là trợ lý thời tiết nhưng hiện KHÔNG kết nối được MCP server nên không có "
            "dữ liệu thời tiết thật. Nói thẳng với người dùng rằng server chưa chạy và hướng "
            "dẫn họ khởi động nó. Tuyệt đối không bịa số liệu thời tiết."
        ),
    )

# Lab 04 — Weather MCP Server + ADK Agent

MCP server tự viết, phục vụ cùng lúc hai loại client: ADK agent (Streamable HTTP) và
Claude Desktop (stdio). Cùng một file server, không sửa dòng nào — đó chính là điều
mà MCP hứa hẹn.

```
                          ┌──────────────────────┐
   Streamable HTTP        │                      │      REST
┌────────────────────────▶│    weather.py        │──────────────▶ WeatherAPI.com
│  localhost:8085/mcp     │    (MCP Server)      │
│                         │                      │
│                         │  3 tools             │
│  ┌──────────────┐       │  3 resources         │
│  │  ADK Agent   │       │  2 prompts           │
│  │ (adk web)    │       └──────────────────────┘
│  └──────────────┘                  ▲
└─────────────────────────           │ stdio
                                     │
                      ┌──────────────┴──────────────┐
                      │  Claude Desktop / Inspector │
                      └─────────────────────────────┘
```

## Server công bố những gì

Bài giảng Ngày 26 nhấn mạnh: **Resources và Prompts bị dùng thiếu, hầu hết team chỉ
dùng Tools**. Server này cố ý dùng cả ba.

### Tools — model quyết định gọi

| Tool | Dùng khi nào |
|---|---|
| `get_current_weather(city)` | Thời tiết ngay lúc này |
| `get_forecast(city, days=3)` | Ngày mai, cuối tuần, lên kế hoạch. `days` 1–3 |
| `health_check()` | Xác minh server sau deploy, chẩn đoán khi tool báo lỗi lạ |

Mỗi docstring nêu rõ **Use this when** và **Do NOT use this for**. Đây không phải
trang trí: LLM chọn tool 100% dựa trên name + description, mô tả mơ hồ dẫn thẳng
tới gọi sai tool.

### Resources — host đọc để lấy context

| URI | Nội dung |
|---|---|
| `weather://schema` | Các trường dữ liệu trả về kèm đơn vị đo, và cấu trúc error envelope |
| `weather://cities` | Bảng ánh xạ tên tiếng Việt sang tên WeatherAPI nhận ("Hà Nội" → "Hanoi") |
| `server://info` | Version thật, transport, giới hạn, tình trạng auth |

Bảng thành phố nằm ở resource thay vì nhồi vào system prompt — thêm thành phố mới
không cần sửa agent.

### Prompts — template dùng lại

| Prompt | Tham số |
|---|---|
| `travel_advice` | `city`, `days` |
| `compare_cities` | `city_a`, `city_b` |

---

## Structured errors, không raise exception

Đây là điểm bài giảng nêu ở slide FastMCP và là chỗ bản đầu của lab làm sai.

Tool **không bao giờ** ném exception qua ranh giới MCP — stack trace không giúp gì
cho LLM. Thay vào đó trả JSON:

```json
{
  "ok": false,
  "error": {
    "code": "city_not_found",
    "message": "No matching location found.",
    "retryable": false,
    "hint": "Kiểm tra chính tả, hoặc thử tên tiếng Anh (Hanoi thay vì Hà Nội)."
  }
}
```

`retryable` là trường quan trọng nhất: nó cho client biết thử lại có ích không.
Timeout và lỗi 5xx của upstream đánh `true`; sai key, sai tên thành phố, hết quota
đánh `false` — retry những cái đó chỉ tốn thời gian.

Instruction của agent dạy Gemini đọc đúng trường này thay vì bịa thời tiết khi tool hỏng.

---

## Setup

### Yêu cầu

- Python ≥ 3.12, [uv](https://docs.astral.sh/uv/)
- Gemini API key — https://aistudio.google.com/apikey
- WeatherAPI key (free tier) — https://www.weatherapi.com/

### Đặt key

Dùng **một** file `.env` ở gốc repo, cả server lẫn client đều tìm ngược lên và đọc được.

PowerShell không có `export`. Dùng:

```powershell
# Từ gốc repo
Set-Content -Path ".env" -Value @(
  "GEMINI_API_KEY=<gemini_key>",
  "WEATHERAPI_KEY=<weatherapi_key>"
) -Encoding ascii
```

`-Encoding ascii` là cố ý. PowerShell 5.1 với `-Encoding utf8` ghi kèm BOM, và
`python-dotenv` sẽ đọc key đầu tiên thành `﻿GEMINI_API_KEY` — sai lặng lẽ,
rất tốn thời gian truy.

`.env` đã nằm trong `.gitignore`, không lọt lên git.

> Chấp nhận cả `GEMINI_API_KEY` lẫn `GOOGLE_API_KEY`. SDK `google-genai` đọc biến
> thứ hai; agent tự ánh xạ sang nếu bạn chỉ đặt biến thứ nhất.

### Chạy

```powershell
# Terminal 1 — MCP server
cd 04-lab\mcp-server
uv sync
uv run python weather.py
# → http://localhost:8085/mcp

# Terminal 2 — smoke test (không cần Gemini key)
cd 04-lab\mcp-server
uv run python test_server.py

# Terminal 3 — ADK agent
cd 04-lab\mcp-client
uv sync
uv run python verify_setup.py     # kiểm trước khi chạy
uv run adk web
# → http://localhost:8000, chọn weather_agent
```

---

## Test bằng MCP Inspector

Bài giảng xếp Inspector vào nhóm **developer essential**: test tool trước khi cắm
vào LLM, tiết kiệm hàng giờ debug. Lý do là Inspector loại bỏ LLM khỏi vòng lặp —
tool sai thì bạn thấy ngay, không phải đoán xem model chọn sai hay tool trả sai.

### Cách 1 — stdio (Inspector tự spawn server)

```powershell
cd 04-lab\mcp-server
npx @modelcontextprotocol/inspector uv run python weather.py --stdio
```

### Cách 2 — Streamable HTTP (server chạy sẵn)

```powershell
# Terminal 1
cd 04-lab\mcp-server
uv run python weather.py

# Terminal 2
npx @modelcontextprotocol/inspector
```

Trong UI: chọn transport **Streamable HTTP**, URL `http://localhost:8085/mcp`, bấm Connect.

### Cần kiểm những gì trong Inspector

Chụp màn hình từng mục để nộp bài:

| Tab | Việc cần làm | Kỳ vọng |
|---|---|---|
| Tools | Xem schema `get_forecast` | `city` bắt buộc, `days` optional default 3 |
| Tools | `get_current_weather` với `city="Hanoi"` | Text có nhiệt độ °C |
| Tools | `get_current_weather` với `city="   "` | JSON `ok:false`, `code:"missing_city"` |
| Tools | `get_forecast` với `days=0` | JSON `code:"invalid_days"` |
| Tools | `get_forecast` với `days=10` | Không lỗi — bị cắt về 3, có ghi chú |
| Resources | Đọc `weather://schema` | JSON mô tả trường + error envelope |
| Resources | Đọc `server://info` | `version: 2.0.0` |
| Prompts | Mở `travel_advice` | Template nhận `city`, `days` |

Ba dòng lỗi ở giữa là phần hay bị bỏ qua nhất. Test đường thành công thì ai cũng
làm; đường lỗi mới là chỗ tool giết chết agent trong production.

### Bản headless

`test_server.py` kiểm đúng những mục trên nhưng chạy bằng lệnh nên bỏ được vào CI:

```powershell
uv run python test_server.py
```

Nó verify handshake, capability negotiation, schema tool, resource, prompt, đường
thành công và **đường lỗi**. Không có `WEATHERAPI_KEY` thì các bước gọi API thật
tự động bỏ qua, phần còn lại vẫn chạy đủ.

---

## Tích hợp Claude Desktop

Cùng file `weather.py`, chỉ khác transport — chạy stdio thay vì HTTP.

1. Mở `claude_desktop_config.json`:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

2. Chép nội dung từ [`claude_desktop_config.json`](claude_desktop_config.json) trong
   thư mục này (đường dẫn đã đúng với máy hiện tại), thay
   `PASTE_YOUR_WEATHERAPI_KEY_HERE` bằng key thật.

3. Khởi động lại Claude Desktop hoàn toàn (thoát hẳn, không chỉ đóng cửa sổ).

4. Kiểm tra: biểu tượng công cụ ở ô nhập liệu hiện `weather` với 3 tool.

Câu hỏi để test E2E:

| Câu hỏi | Chứng minh điều gì |
|---|---|
| "Thời tiết Hà Nội thế nào?" | Routing sang `get_current_weather`, chuẩn hoá "Hà Nội" → "Hanoi" |
| "Cuối tuần này Đà Nẵng có mưa không?" | Routing sang `get_forecast`, không nhầm sang tool current |
| "So sánh Hà Nội với Đà Lạt ngay bây giờ" | **Multi-tool routing** — hai lượt gọi rồi tổng hợp |
| "Server thời tiết còn sống không?" | Routing sang `health_check` |

Câu thứ ba là câu quan trọng nhất cho phần nộp bài: nó chứng minh model tự điều
phối nhiều lượt gọi tool, không phải chỉ một phát ăn ngay.

> `env` trong config đặt `WEATHERAPI_KEY` trực tiếp vì Claude Desktop spawn server
> ở thư mục làm việc khác, `find_dotenv()` có thể không tới được `.env` ở gốc repo.

---

## stdio hay HTTP — chọn cái nào

| | stdio | Streamable HTTP |
|---|---|---|
| Ai khởi động server | Host tự spawn | Bạn chạy sẵn như một dịch vụ |
| Phù hợp | Claude Desktop, Inspector, script local | ADK agent, nhiều client dùng chung, remote |
| Auth | Không cần — cùng máy, cùng ranh giới tin cậy | **Bắt buộc** nếu ra khỏi localhost |
| Trong lab này | `uv run python weather.py --stdio` | `uv run python weather.py` |

SSE là đường cũ, nhiều client đã coi là legacy. Server này dùng `streamable-http`.

Server hiện **không có auth** vì chỉ chạy localhost. Đưa ra internet mà không thêm
auth là mở cho cả thế giới gọi tool nội bộ của bạn — xem [`03-production/`](../03-production/)
để biết cách gắn bearer token.

---

## Troubleshooting

**`UnicodeEncodeError: 'charmap' codec can't encode character`**
Console Windows mặc định cp1252, không in được tiếng Việt. Ba script trong lab đã
tự `reconfigure` stdout/stderr sang UTF-8. Nếu bạn viết script mới thì thêm:

```python
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
```

**`GET /mcp` trả `406 Not Acceptable`**
Bình thường. Endpoint MCP không phục vụ GET của trình duyệt — nó cần header
`Accept: text/event-stream` và bắt tay JSON-RPC. Dùng `test_server.py` hoặc Inspector,
đừng mở URL bằng trình duyệt.

**Agent chạy nhưng nói không có tool**
`agent.py` rơi vào fallback vì không kết nối được server. Khởi động server trước,
rồi chạy lại `adk web`. Chạy `verify_setup.py` để biết bước nào hỏng.

**Tool trả `missing_api_key`**
Server không thấy `WEATHERAPI_KEY`. Kiểm bằng `health_check` — trường
`api_key_configured` sẽ là `false`. Server đọc `.env` lúc khởi động, nên sửa `.env`
xong phải restart server.

**Port 8085 bận**
Đặt `PORT` cho server và `MCP_SERVER_URL` cho client:

```powershell
$env:PORT = "8090"
$env:MCP_SERVER_URL = "http://localhost:8090/mcp"
```

---

## Đối chiếu với yêu cầu Lab #26

| Yêu cầu | Ở đâu |
|---|---|
| Build MCP server, 3 tools | [`mcp-server/weather.py`](mcp-server/weather.py) |
| Add Resource cho dynamic context | 3 resource, xem mục Resources ở trên |
| Test với Inspector — schema, calls, error responses | Mục Inspector; bản headless ở [`mcp-server/test_server.py`](mcp-server/test_server.py) |
| Claude Desktop config + E2E multi-tool routing | [`claude_desktop_config.json`](claude_desktop_config.json) và mục tích hợp |
| Cross-client compatibility | Cùng server phục vụ ADK (HTTP) và Claude Desktop (stdio) |
| README có tool descriptions | Mục "Server công bố những gì" |

Còn phải tự làm: chụp màn hình Inspector, quay video demo Claude Desktop 2 phút.

## Cấu trúc

```
04-lab/
├── README.md
├── claude_desktop_config.json     # config mẫu, đường dẫn đã đúng máy này
├── mcp-server/
│   ├── weather.py                 # server: 3 tools, 3 resources, 2 prompts
│   ├── test_server.py             # smoke test headless, kiểm cả đường lỗi
│   ├── Dockerfile
│   └── pyproject.toml
└── mcp-client/
    ├── weather_agent/agent.py     # ADK agent đóng vai MCP client
    ├── verify_setup.py            # kiểm setup, bắt tay MCP thật
    ├── e2e_check.py               # hỏi thật qua Gemini, in ra tool nào được gọi
    └── pyproject.toml
```

## Ba script kiểm tra, ba tầng khác nhau

| Script | Chạy ở đâu | Kiểm tầng nào | Cần Gemini key |
|---|---|---|---|
| `mcp-server/test_server.py` | mcp-server | Giao thức MCP: schema, resource, prompt, đường lỗi | Không |
| `mcp-client/verify_setup.py` | mcp-client | Môi trường, thư viện, bắt tay được với server chưa | Không |
| `mcp-client/e2e_check.py` | mcp-client | Vòng lặp thật: Gemini chọn tool nào cho câu hỏi nào | Có |

`e2e_check.py` là cái chứng minh phần khó nhất — model có route đúng không. Nó in ra
tool call thật cho từng câu hỏi:

```
HOI: Thời tiết Hà Nội bây giờ thế nào?
TOOL CALLS: ["get_current_weather({'city': 'Hanoi'})"]

HOI: Cuối tuần này Đà Nẵng có mưa không?
TOOL CALLS: ["get_forecast({'days': 3, 'city': 'Da Nang'})"]
```

Đây là bằng chứng cho ba điều cùng lúc: chuẩn hoá tên thành phố hoạt động, model
phân biệt được "bây giờ" với "cuối tuần", và tool description đủ rõ để chọn đúng.

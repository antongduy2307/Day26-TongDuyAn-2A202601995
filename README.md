# Phân biệt MCP và Function Calling

Đây là hai khái niệm hay bị nhầm lẫn nhưng thực ra ở **hai tầng khác nhau**, và **bổ sung cho nhau** chứ không thay thế.

## Cấu trúc repo

```
day26-mcp/
├── README.md                ← Bạn đang đọc file này
├── requirements.txt         ← pip install -r requirements.txt
│
├── 01-function-calling/     ← Bước 1: Function Calling thuần (Gemini SDK)
│   ├── README.md
│   └── weather_function_calling.py
│
├── 02-mcp-basics/           ← Bước 2: MCP server + client (không cần API key)
│   ├── README.md
│   ├── weather_server.py
│   └── weather_client.py
│
├── 03-production/           ← Bước 3: Auth, Tool Registry, Versioning
│   ├── README.md
│   ├── auth_server.py
│   ├── auth_client.py
│   ├── registry.json
│   ├── registry_client.py
│   └── versioned_server.py
│
└── 04-lab/                  ← Bước 4: Lab — server thật, 2 client, Inspector
    ├── README.md
    ├── claude_desktop_config.json
    ├── mcp-server/          ← 3 tools + 3 resources + 2 prompts
    └── mcp-client/          ← ADK agent đóng vai MCP client
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# MCP demo (không cần API key)
cd 02-mcp-basics && python weather_client.py

# Function Calling (cần Gemini API key)
export GEMINI_API_KEY=...
cd 01-function-calling && python weather_function_calling.py

# Production — Auth (2 terminal)
cd 03-production
python auth_server.py              # terminal 1
python auth_client.py              # terminal 2

# Production — Tool Registry
cd 03-production && python registry_client.py
```

Lab 04 dùng `uv` thay vì pip, và chạy trên PowerShell (xem [`04-lab/README.md`](04-lab/README.md)):

```powershell
cd 04-lab\mcp-server ; uv sync ; uv run python weather.py      # terminal 1
cd 04-lab\mcp-server ; uv run python test_server.py            # terminal 2
cd 04-lab\mcp-client ; uv sync ; uv run adk web                # terminal 3
```

---

## Định nghĩa ngắn gọn

**Function Calling** là một *khả năng của model* (capability). Model được huấn luyện để khi bạn đưa cho nó danh sách các "công cụ" (kèm schema mô tả tham số), nó có thể tự quyết định gọi công cụ nào và sinh ra JSON tham số phù hợp. Bản thân model **không chạy** function — nó chỉ nói "hãy gọi `get_weather(city='Hanoi')`". App mới là nơi chạy tool.

**MCP (Model Context Protocol)** là một *giao thức chuẩn* (protocol) — giống như USB-C hay HTTP cho thế giới AI. Nó định nghĩa cách một **MCP Client** (như Claude Code, Claude Desktop) kết nối tới các **MCP Server** để khám phá và sử dụng tools, resources, prompts một cách thống nhất.

---

## So sánh trực tiếp

| Tiêu chí | Function Calling | Model Context Protocol (MCP) |
|---|---|---|
| **Bản chất** | Tính năng của mô hình (Model capability) | Giao thức giao tiếp client–server |
| **Ai định nghĩa tool?** | Bạn hard-code trong từng app | Server tự công bố (self-describe) tool |
| **Tái sử dụng** | Phải viết lại cho mỗi app/model | Viết 1 lần, mọi MCP client dùng được |
| **Thực thi** | App của bạn tự chạy | MCP Server chạy, client điều phối |
| **Tính chuẩn hóa** | Mỗi nhà cung cấp 1 kiểu (OpenAI, Anthropic khác nhau) | Một chuẩn chung do Anthropic đề xuất |
| **Hệ sinh thái** | Khó chia sẻ dạng module đóng gói sẵn | Dễ dàng chia sẻ và tải về các "MCP Servers" mã nguồn mở |

## Quan hệ giữa chúng

Điểm quan trọng nhất: **MCP dùng Function Calling bên dưới**. Chúng không loại trừ nhau.

```
User hỏi
   │
   ▼
LLM (dùng Function Calling để quyết định gọi tool nào)
   │
   ▼
MCP Client  ──[giao thức MCP]──►  MCP Server (thực thi tool thật)
   │                                   │
   ◄───────────── kết quả ─────────────┘
   ▼
LLM tổng hợp câu trả lời
```

## Khi nào dùng cái nào?

- **Function Calling thuần**: app đơn giản, tool gắn chặt với 1 ứng dụng, không cần chia sẻ.
- **MCP**: muốn tool/tích hợp dùng lại được trên nhiều AI client, muốn tách biệt logic tool khỏi app, hoặc xây hệ sinh thái tích hợp (DB, file, API nội bộ...).

---

## Minh hoạ bằng mã nguồn

Cùng một tool `get_weather`, dưới đây là hai cách triển khai để thấy rõ sự khác biệt.

### [Cách 1 — Function Calling thuần (Google Gemini SDK)](01-function-calling/)

Tool được **định nghĩa và thực thi ngay trong app**. Model chỉ quyết định gọi tool nào, app tự chạy và đưa kết quả trở lại.

```
User hỏi → Model quyết định gọi get_weather("Hà Nội")
                    │
                    ▼
             App TỰ THỰC THI hàm get_weather
                    │
                    ▼
             Model tổng hợp câu trả lời
```

> Nhược điểm: schema viết tay, tool gắn chặt trong app — muốn dùng lại ở app khác phải copy cả schema lẫn hàm.

Chi tiết + code: xem [`01-function-calling/README.md`](01-function-calling/README.md)

### [Cách 2 — MCP (server tự công bố tool, mọi client dùng chung)](02-mcp-basics/)

Tool được tách ra **một MCP server độc lập**. Server tự "khai báo" nó có tool gì; bất kỳ MCP client nào (Claude Code, Claude Desktop, Cursor...) cũng cắm vào dùng được mà không cần biết code bên trong.

```
weather_client.py                       weather_server.py
┌─────────────┐    giao thức MCP    ┌─────────────────┐
│  list_tools │ ──────────────────▶ │ @mcp.tool()     │
│  call_tool  │ ◀────────────────── │ get_weather()   │
└─────────────┘     stdio           └─────────────────┘
```

Chi tiết + code: xem [`02-mcp-basics/README.md`](02-mcp-basics/README.md)

### Điểm khác biệt rút ra từ code

| | Function Calling thuần | MCP |
|---|---|---|
| Khai báo schema | Tự viết tay trong app | `@mcp.tool()` tự sinh từ type hints |
| Nơi thực thi tool | Trong app gọi model | Trong MCP server riêng |
| Khám phá tool | Hard-code danh sách `tools` | `session.list_tools()` tại runtime |
| Dùng lại ở app khác | Copy code | Cắm thêm client, không sửa server |
| Vai trò Function Calling | Là toàn bộ cơ chế | Là lớp model bên trong MCP |

---

## [MCP trong Production](03-production/)

Các ví dụ trên chạy tốt trên máy cá nhân, nhưng đưa vào **hệ thống production** cần giải quyết thêm ba vấn đề:

```
┌─────────────────────────────────────────────────────┐
│                  Production MCP                     │
│                                                     │
│  ┌──────────┐   ┌───────────┐   ┌───────────────┐   │
│  │ Security │   │ Registry  │   │  Versioning   │   │
│  │          │   │           │   │               │   │
│  │ • Auth   │   │ • Discover│   │ • v1 compat   │   │
│  │ • Token  │   │ • Connect │   │ • v2 features │   │
│  │ • Scopes │   │ • Health  │   │ • Deprecation │   │
│  └──────────┘   └───────────┘   └───────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 1. Security — Authentication & Authorization

MCP server phục vụ qua **HTTP** cho nhiều client → cần xác thực. MCP SDK hỗ trợ sẵn **Bearer Token** verification:

- Server: cấu hình `AuthSettings` + implement `TokenVerifier` protocol
- Client: gửi header `Authorization: Bearer <token>` qua `httpx.AsyncClient`
- Không có token → 401, token sai → 403, logic tool không biết gì về auth

| Tầng | Demo (stdio) | Production (HTTP) |
|---|---|---|
| Transport | stdio (cùng máy) | Streamable HTTP (qua mạng) |
| Auth | Không cần | Bearer token / OAuth / mTLS |
| Phạm vi truy cập | Toàn bộ | Scopes giới hạn từng client |

### 2. Tool Registry & Discovery

Agent **không hard-code** tool nào. Nó hỏi **Tool Registry** — danh mục trung tâm liệt kê tất cả tool từ mọi server — theo yêu cầu task:

```
Agent nhận task "lấy thời tiết Hà Nội"
   │
   ▼
Tool Registry: "tool nào có tag 'weather'?"
   │
   ├── get_weather v1.0 → server: weather (stdio)
   └── get_weather_v2 v2.0 → server: weather-v2 (stdio)
   │
   ▼
Agent chọn best match (v2.0, không deprecated)
   │
   ▼
Kết nối tới server weather-v2, gọi get_weather_v2(city="Hanoi")
```

Registry là **tool-centric** — đơn vị khám phá là **tool** (tag, description, parameters), không phải server.

| | Hard-code (demo) | Tool Registry (production) |
|---|---|---|
| Agent biết tool nào? | Chỉ tool được code sẵn | Tất cả tool trong registry |
| Tìm tool | Theo tên cố định | Theo tag, keyword, capability |
| Thêm tool mới | Sửa code agent | Thêm entry vào registry |
| Chọn tool | Developer quyết định | Agent tự chọn best match |

### 3. Versioning & Backward Compatibility

Server v1 có `get_weather(city)` trả chuỗi đơn giản. V2 muốn trả JSON chi tiết, thêm `include_forecast`. Nếu đổi trực tiếp → mọi client cũ break. Giải pháp — 3 kỹ thuật kết hợp:

| Kỹ thuật | Mô tả |
|---|---|
| **Tool mới song song** | `get_weather_v2` tồn tại bên cạnh `get_weather` — không xoá tool cũ |
| **Tham số optional** | `include_forecast`, `units` có default → client cũ gọi vẫn đúng |
| **Server metadata** | Resource `server://info` công bố version + deprecation notice |

Chi tiết + code cho cả 3 phần: xem [`03-production/README.md`](03-production/README.md)

### Tổng kết Production Checklist

| Khía cạnh | Dev/Demo | Production |
|---|---|---|
| **Transport** | stdio (cùng máy) | HTTP/SSE (qua mạng) |
| **Auth** | Không | Bearer token, OAuth, mTLS |
| **Discovery** | Hard-code tool/server | Tool Registry — agent tìm tool theo task |
| **Versioning** | 1 tool duy nhất | Tool v1 + v2 song song, deprecation notice |
| **Health** | Không | Health check, retry, circuit breaker |
| **Logging** | `print()` | Structured logging, tracing (OpenTelemetry) |

---

## [Lab thực hành](04-lab/)

Server thật gọi WeatherAPI.com, phục vụ đồng thời hai client qua hai transport khác nhau
mà không sửa dòng code nào — đó là điều MCP hứa hẹn, và lab này kiểm chứng nó.

```
   Streamable HTTP  ┌──────────────┐  stdio
  ┌────────────────▶│  weather.py  │◀────────────────┐
  │  :8085/mcp      │              │                 │
┌─┴──────────┐      │ 3 tools      │      ┌──────────┴──────────┐
│ ADK Agent  │      │ 3 resources  │      │ Claude Desktop      │
│ (adk web)  │      │ 2 prompts    │      │ / MCP Inspector     │
└────────────┘      └──────────────┘      └─────────────────────┘
```

Điểm khác ba bài trước: có **Resources và Prompts** (không chỉ Tools), có **structured
error** thay vì chuỗi lỗi, và có **test đường lỗi** chứ không chỉ đường thành công.

---

## Vấn đề N×M — gốc rễ của MCP

Trước MCP, mỗi cặp (AI provider × công cụ) cần một adapter riêng:

```
Trước MCP: N×M adapter              Sau MCP: N+M adapter

OpenAI    ─┬─ Database              OpenAI    ─┐         ┌─ Database
Anthropic ─┼─ GitHub                Anthropic ─┼── MCP ──┼─ GitHub
Google    ─┴─ Slack                 Google    ─┘         └─ Slack

3 × 3 = 9 adapter                   3 + 3 = 6 adapter
Thêm 1 provider = viết 3 cái mới    Thêm 1 provider = viết 1 cái
```

Con số nhỏ ở ví dụ này nhưng tăng theo tích. 10 provider × 20 tool = 200 adapter,
so với 30. Đây chính là điều mà "USB-C cho AI" nói tới.

---

## Kiến trúc Host, Client, Server

Ba vai khác nhau, hay bị gộp làm một khi mới học:

```
┌──────────────────┐
│      HOST        │  Claude Desktop, Cursor, ADK — nơi chứa LLM và giao diện
│  (LLM + UI)      │
└────────┬─────────┘
         │ tạo ra, mỗi server một client
    ┌────┴────┬──────────┐
    ▼         ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│Client 1│ │Client 2│ │Client 3│  giữ 1:1 một kết nối, nói JSON-RPC 2.0
└───┬────┘ └───┬────┘ └───┬────┘
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│Server  │ │Server  │ │Server  │  chạy tool thật, không biết gì về LLM
│postgres│ │github  │ │weather │
└────────┘ └────────┘ └────────┘
```

| Ranh giới tin cậy | Nội dung |
|---|---|
| Host **tin** Client | Cùng process, cùng chủ sở hữu |
| Client **xác minh** Server | Auth, kiểm danh tính, kiểm capability |
| Server **validate mọi input** | Không giả định client lành tính |

Giao thức bên dưới là **JSON-RPC 2.0** — cùng một định dạng thông điệp cho cả stdio
lẫn HTTP. Đổi transport không đổi ngữ nghĩa.

**Capability negotiation**: lúc `initialize`, client và server khai báo chúng hỗ trợ gì
trước khi dùng. Nhờ vậy client mới nói chuyện được với server cũ và ngược lại.

---

## Sáu primitive của MCP

Đây là điểm bị bỏ sót nhiều nhất. Hầu hết team chỉ dùng Tools rồi kết luận
"MCP chỉ là function calling đổi tên" — bỏ lỡ đúng phần quan trọng.

| Primitive | Ai kiểm soát | Vai trò | Ví dụ |
|---|---|---|---|
| **Tools** | LLM quyết định gọi | Hành động hoặc truy vấn | `query_db()`, `send_email()` |
| **Resources** | App/host chủ động đọc | Dữ liệu chỉ đọc theo URI | `file://docs/guide.md` |
| **Prompts** | User chọn | Template tương tác dùng lại | template `summarize-code` |
| **Roots** | Client chia sẻ | Phạm vi workspace an toàn cho server | thư mục dự án đang mở |
| **Sampling** | Server yêu cầu | Server nhờ host/LLM suy luận hộ | server cần tóm tắt trước khi trả |
| **Elicitation** | Server hỏi user | Xin thêm thông tin qua UI của host | form nhập ngày tháng |

Ba cái đầu trả lời: **server cung cấp được gì cho host?**
Ba cái sau trả lời: **server cần host hỗ trợ gì để hoàn tất công việc?**

MCP là giao thức **trao đổi context**, không chỉ giao thức gọi tool. Dùng Resources
cho dynamic context injection thay vì hardcode vào system prompt — xem
[`04-lab/`](04-lab/) làm mẫu.

---

## MCP Inspector — công cụ bắt buộc

Test tool **trước khi** cắm vào LLM. Lý do: khi agent trả lời sai, bạn không phân biệt
được model chọn sai tool hay tool trả sai dữ liệu. Inspector loại LLM khỏi vòng lặp
nên câu trả lời rõ ngay.

```bash
npx @modelcontextprotocol/inspector python weather_server.py
```

Thứ tự debug hiệu quả: **Inspector trước → log của client → trace ở tầng cao hơn**.

Cần kiểm cả ba: schema tool đúng chưa, output format đúng chưa, và **error response**
trông thế nào. Mục thứ ba hay bị bỏ, mà đó lại là chỗ tool giết agent trong production.

Bản chạy bằng lệnh: [`04-lab/mcp-server/test_server.py`](04-lab/mcp-server/test_server.py).

---

## Sáu anti-pattern về bảo mật

| Anti-pattern | Vì sao nguy hiểm |
|---|---|
| Expose MCP server ra internet không auth | Chấp nhận cho cả thế giới gọi tool nội bộ |
| Tin "read-only" là tuyệt đối an toàn | Prompt injection biến đường đọc thành đường rò dữ liệu |
| Nhồi quá nhiều tool vào context | Model đốt token đọc catalog thay vì giải task |
| Tool description mơ hồ | Model gọi sai tool dù backend hoàn toàn đúng |
| Không log/audit tool call | Có sự cố thì không biết tool nào đã chạy |
| Trộn credential sandbox với production | Thử nghiệm local nhưng cầm token prod full quyền |

Bốn tầng phòng thủ, xếp chồng chứ không thay thế nhau:

```
1. Transport   OAuth 2.0 cho HTTP, TLS
2. Validation  validate mọi input ở phía server
3. Permission  mỗi tool chỉ đúng quyền cần thiết
4. Audit       log mọi lần gọi tool kèm kết quả
```

stdio chạy local không cần OAuth. HTTP ra khỏi máy thì **bắt buộc**.

Tin tưởng người viết MCP server là **cần** nhưng **không đủ** — vẫn phải có
permissioning, review output, xác nhận trước khi ghi, và audit.

---

## MCP năm 2026 — khác gì giai đoạn đầu

| Thay đổi | Nội dung |
|---|---|
| Transport | Remote production nghiêng hẳn về `streamable-http`; SSE thành legacy ở nhiều client |
| Capability negotiation | Trở thành tư duy cốt lõi, không phải chi tiết kỹ thuật phụ |
| Không chỉ tools | Resources, prompts, roots, sampling, elicitation đều có vai trò thật |
| Scale problem | Host có hàng trăm tool thì context window và latency thành nút thắt |
| Governance | Chuyển vào Agentic AI Foundation (Linux Foundation) để tránh khoá theo một vendor |

Hệ sinh thái: 10.000+ server công khai, 97 triệu lượt tải SDK mỗi tháng. Đã đi từ
"giao thức của Anthropic" sang chuẩn trung lập — ChatGPT, Cursor, Gemini, Microsoft
Copilot, VS Code đều đã hỗ trợ. **A2A** (Agent-to-Agent) bổ sung cho MCP ở mảng
agent nói chuyện với agent.

### Server hay dùng trong thực tế

| Server | Dùng để làm gì | Khi nào nên dùng |
|---|---|---|
| GitHub MCP | Repo, issue, PR, code search | Vòng lặp ticket → code → PR |
| Sentry MCP | Error, stack trace, release regression | Debug sự cố production rồi mở fix ngay |
| Context7 MCP | Docs của thư viện theo đúng version | Framework thay đổi nhanh |
| Playwright MCP | Browser automation, E2E check | Tái hiện bug UI và verify fix |
| Slack / Notion MCP | Chat, spec, wiki context | Lấy quyết định, requirement, handoff |

Chọn server theo **workflow thật**, không cài cho có. Nhồi một "tool zoo" không gắn
với task nào chỉ làm agent chậm và chọn sai.

### Ba workflow có ROI cao

1. **Ticket → code → PR**: GitHub MCP + docs MCP
2. **Prod error → root cause**: Sentry MCP + GitHub MCP
3. **Library upgrade → migration**: Context7 + Playwright MCP

Điểm chung: đều là **closed loop** — đọc đúng context, hành động nhỏ, verify ngay.
MCP mạnh nhất khi có feedback loop, không phải khi có nhiều tool.

---

## Production checklist

- [ ] Bắt đầu từ workflow thật, không từ danh sách tool muốn có
- [ ] Tool name + description viết cho model chọn đúng ngay lần đầu
- [ ] Output gọn; payload thô để trong resource hoặc fetch-on-demand
- [ ] Dùng Inspector trước khi test trong client thật
- [ ] Transport đúng chỗ: stdio cho local, HTTP cho dịch vụ dùng chung
- [ ] Tách scope đọc/ghi, log mọi hành động ghi, có xác nhận của người khi cần
- [ ] Lỗi trả structured, không raise exception qua ranh giới MCP
- [ ] Với Claude Code/Codex: hướng dẫn agent bằng server naming, instructions, `AGENTS.md`, hooks

---

**Tóm lại:** Function Calling là *cơ chế model gọi công cụ*; MCP là *chuẩn để kết nối model với các công cụ đó* — và MCP thực chất dùng Function Calling làm nền tảng để hoạt động.

Nhưng nếu chỉ dừng ở đó thì bỏ lỡ phần quan trọng nhất. MCP không phải "function calling
đổi tên": nó thêm **tool discovery** lúc runtime, **context control** qua resources và
prompts, và **khả năng tương thích chéo giữa nhiều client**.

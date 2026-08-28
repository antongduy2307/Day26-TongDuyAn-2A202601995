"""E2E: hoi that -> Gemini chon tool -> goi MCP server -> tra loi."""
import asyncio, sys
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        s.reconfigure(encoding="utf-8", errors="replace")

from google.adk.runners import InMemoryRunner
from google.genai import types
from weather_agent import root_agent

QUESTIONS = [
    "Thời tiết Hà Nội bây giờ thế nào?",
    "Cuối tuần này Đà Nẵng có mưa không?",
    "So sánh thời tiết Hà Nội với Đà Lạt ngay bây giờ",   # multi-tool routing
    "Thời tiết ở Xyzzyville Nonexistent thế nào?",         # đường lỗi
    "Server thời tiết còn sống không?",
]

async def ask(runner, uid, q):
    sess = await runner.session_service.create_session(app_name="weather", user_id=uid)
    msg = types.Content(role="user", parts=[types.Part(text=q)])
    calls, final = [], ""
    async for ev in runner.run_async(user_id=uid, session_id=sess.id, new_message=msg):
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                if p.function_call:
                    calls.append(f"{p.function_call.name}({dict(p.function_call.args)})")
        if ev.is_final_response() and ev.content and ev.content.parts:
            final = "".join(p.text or "" for p in ev.content.parts)
    return calls, final

async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="weather")
    for q in QUESTIONS:
        print(f"\n{'='*60}\nHOI: {q}")
        calls, final = await ask(runner, "tester", q)
        print(f"TOOL CALLS: {calls or 'KHONG GOI TOOL NAO'}")
        print(f"TRA LOI: {final.strip()[:400]}")

asyncio.run(main())

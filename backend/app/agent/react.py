"""ReAct 循环。

流程：
  1. 把 system prompt + 用户消息 + 工具 schema 发给模型
  2. 模型可能直接回答，也可能要求调用工具
  3. 如果调用了工具 → 执行工具 → 把结果作为 tool 消息追加 → 再问模型
  4. 重复直到模型不再调用工具，或达到最大轮数（防死循环）

输出用 SSE 流式，事件类型：
  - {"type": "text", "content": "..."}              模型输出的文字
  - {"type": "tool_call", "name": "...", "args": ...} 模型要调用工具
  - {"type": "tool_result", "name": "...", "result": ...} 工具执行结果
  - {"type": "error", "content": "..."}              出错
  - {"type": "done"}                                 结束
"""

import json

import ollama

from app.agent.tools import ToolContext, execute_tool

# 最大工具调用轮数，防止模型死循环
MAX_ITERATIONS = 5


def run_react_stream(
    client: ollama.Client,
    model: str,
    system_prompt: str,
    user_messages: list[dict],
    tools_schema: list[dict],
    tool_context: ToolContext,
):
    """生成器，yield SSE 格式的字符串。"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(user_messages)

    # 文本缓冲区：攒够 4 个字符或遇标点/换行才发，减少 SSE 事件数量
    pending = ""

    def flush_pending():
        nonlocal pending
        if pending:
            yield _sse({"type": "text", "content": pending})
            pending = ""

    for iteration in range(MAX_ITERATIONS):
        try:
            stream = client.chat(
                model=model,
                messages=messages,
                tools=tools_schema,
                stream=True,
            )
        except Exception as e:
            yield _sse({"type": "error", "content": f"模型调用失败：{e}"})
            return

        content_buffer = ""
        tool_calls: list[dict] = []

        for chunk in stream:
            msg = chunk.get("message", {})

            # 文本片段
            text = msg.get("content", "")
            if text:
                content_buffer += text
                pending += text

                # 攒够 4 字，或遇到标点/换行，就发出去
                if len(pending) >= 4 or any(
                        ch in "，。！？；：、,.!?;:\n " for ch in text
                ):
                    yield _sse({"type": "text", "content": pending})
                    pending = ""

            # 工具调用（Ollama 流式里 tool_calls 通常一次给完整）
            for tc in (msg.get("tool_calls") or []):
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_raw = fn.get("arguments", {})

                # arguments 可能是 dict 或 JSON 字符串
                if isinstance(args_raw, str):
                    try:
                        args_raw = json.loads(args_raw)
                    except Exception:
                        args_raw = {}

                if name:
                    tool_calls.append({"name": name, "args": args_raw})

        # 把助手这轮输出加入历史
        assistant_msg: dict = {"role": "assistant", "content": content_buffer}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["args"],
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        # 没有工具调用 → 结束前把缓冲清空
        if not tool_calls:
            if pending:
                yield _sse({"type": "text", "content": pending})
                pending = ""
            yield _sse({"type": "done"})
            return

        # 工具调用前，把残留的文字先发出去
        if pending:
            yield _sse({"type": "text", "content": pending})
            pending = ""

        # 执行工具
        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]

            yield _sse({"type": "tool_call", "name": name, "args": args})

            result = execute_tool(name, args, tool_context)

            yield _sse({"type": "tool_result", "name": name, "result": result})

            messages.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
            })

    if pending:
        yield _sse({"type": "text", "content": pending})
        pending = ""
    yield _sse({"type": "error", "content": "已达到最大工具调用轮数"})
    yield _sse({"type": "done"})


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
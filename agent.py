import anthropic
from tools import Tools, run_tool, prompt
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
import time

CRITIC_PROMPT = """你是一位严格的代码/任务审查员。请检查以下助手的回答：
1. 是否真的解决了用户最初的请求？
2. 是否有未处理的边界情况或事实错误？
3. 是否有更简单/更正确的做法？

如果完全没问题，只回复一个词：APPROVED
否则，按编号列出具体问题，简洁直接。"""

MAX_CRITIC_ROUNDS = 3

console = Console()
import os

client = anthropic.Anthropic(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
)

# 对话历史
messages = []

def critic(msg : str) -> str:
    client.messages.create(
        model = "deepseek-v4-pro",
        system = CRITIC_PROMPT,
        max_tokens = 1024,
        messages = msg
    )
    text_parts = [b.text for b in response.content if b.type == "text"]
    return "".join(text_parts)

# ── 全局Token 用量统计 ──
total_input_tokens = 0
total_output_tokens = 0

while True:
    # 1. 拿用户输入
    user_input = input(">>> ")

    critic_rounds = 0
    # 2. 退出判断
    if user_input == "/exit":
        print(f"\n 本轮会话总计: input={total_input_tokens} tokens  output={total_output_tokens}  tokens")
        break

    turn_in = 0
    turn_out = 0

    # 3. 把用户的话加到 messages
    messages.append({
        "role": "user",
        "content": user_input
    })

    while True:
        # 4. 调 API
        with client.messages.stream(
                model = "deepseek-v4-pro",
                system = prompt,
                max_tokens = 8192,
                tools = Tools,
                messages = messages
        ) as stream:
            iterator = iter(stream.text_stream)

            #  转圈等第一个 chunk
            with console.status("[dim]Thinking…[/dim]", spinner="dots"):
                try:
                    first_text = next(iterator)
                except StopIteration:
                    first_text = None  # 一个 chunk 都没有（比如纯 tool_use）
            # ← status 在这里退出，那行消失

            #  有内容才开 Live
            if first_text is not None:
                full_text = first_text
                with Live(Markdown(full_text), console=console, refresh_per_second=10) as live:
                    for text in iterator:  # 用剩下的 iterator 继续
                        full_text += text
                        live.update(Markdown(full_text))

            print()
            with console.status("[dim]Producing…[/dim]", spinner="dots"):
                response = stream.get_final_message()

        # ── Token 用量统计 ──
        usage = response.usage
        in_tok = usage.input_tokens
        out_tok = usage.output_tokens
        turn_in += in_tok
        turn_out += out_tok
        total_input_tokens += in_tok
        total_output_tokens += out_tok


        # 6. 把模型的回复加到 messages
        messages.append({
            "role": "assistant",
            "content": response.content
        })

        # 7. 没工具要调,跳出内层循环回到等用户输入
        if response.stop_reason == "end_turn":
            if critic_rounds >= MAX_CRITIC_ROUNDS:
                break
            with console.status("[dim]Auditing…[/dim]", spinner="dots"):
                text = critic(messages)
            if "APPROVED" in text.upper():
                break
            console.print(f"[dim]审查反馈: {text}[/dim]")
            messages.append({
                "role": "user",
                "content": f"审查员反馈：{text}\n请根据反馈修正你的回答。"
            })
            critic_rounds += 1
            continue

        # 8. 工具调用:统一交给 run_tool 分发
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                console.print(f"[dim]→ {block.name}({str(block.input)[:60]})[/dim]")
                if block.name == "run_cmd":
                    confirm = input(f"是否执行命令 `{block.input['cmd']}` ?(y/n): ").strip().lower()
                    if confirm != "y":
                        result = "用户拒绝命令"
                        console.print(f"用户取消命令")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })
                        continue
                with console.status(f"[dim]running {block.name}…[/dim]", spinner="dots"):
                    result = run_tool(block.name, block.input)
                console.print(f"[dim]  ✓ done ({len(result)} chars)[/dim]")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

            # 工具结果以 user 角色发回模型,继续内层循环
            messages.append({
                "role": "user",
                "content": tool_results
            })

        else:
            # max_tokens / stop_sequence / refusal / 其他
            print(f"  异常停止: {response.stop_reason}")
            messages.pop()
            break
    console.print(f"[dim]↑ {turn_in} tokens  ↓ {turn_out} tokens[/dim]")
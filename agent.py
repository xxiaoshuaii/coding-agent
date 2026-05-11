import anthropic
from tools import Tools, run_tool, prompt
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

console = Console()

import os

client = anthropic.Anthropic(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
)
messages = []  # 对话历史

while True:
    # 1. 拿用户输入
    user_input = input(">>> ")

    # 2. 退出判断
    if user_input == "/exit":
        break

    # 3. 把用户的话加到 messages
    messages.append({
        "role": "user",
        "content": user_input
    })

    while True:
        # 4. 调 API
        with client.messages.stream(
                model="deepseek-v4-flash",
                system=prompt,
                max_tokens=8192,
                tools=Tools,
                messages=messages,
        ) as stream:
            with Live(Markdown(""), console=console, refresh_per_second=10) as live:
                full_text = ""
                for text in stream.text_stream:
                    full_text += text
                    live.update(Markdown(full_text))
            print()
            response = stream.get_final_message()

        # 6. 把模型的回复加到 messages
        messages.append({
            "role": "assistant",
            "content": response.content
        })

        # 7. 没工具要调,跳出内层循环回到等用户输入
        if response.stop_reason == "end_turn":
            break

        # 8. 工具调用:统一交给 run_tool 分发
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = run_tool(block.name, block.input)
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
            print(f"⚠️  异常停止: {response.stop_reason}")
            messages.pop()
            break

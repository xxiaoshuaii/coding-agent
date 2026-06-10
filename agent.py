import anthropic
from tools import Tools, run_tool, prompt
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from session.session import SessionManager
import questionary
import time
import sys

kb = KeyBindings()


@kb.add("c-j")  # Ctrl+J 换行
def _(event):
    event.current_buffer.insert_text("\n")


console = Console()
import os

client = anthropic.Anthropic(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
)

# 对话历史
messages = []
# 记ctrl+c
last_interrupt = 0.0
# 方便同意命令
approve_cmds = set()
# 启动时自动恢复上次会话
session_mgr = SessionManager()
files = sorted(
    session_mgr.dir.glob("*.json"),
    key = lambda f:f.stat().st_mtime,
    reverse = True,
)
if files:
    choices = [f.stem for f in files] + ["+ 新建会话"]
    choice = questionary.select("选择会话:",choices = choices).ask()
    if choice is None or choice == "+ 新建会话":
        messages = []
    else:
        messages = session_mgr.load(choice)
        console.print(f"[dim]📂 已加载 [{choice}],{len(messages)} 条消息[/dim]")
else:
    messages = []



# ── 全局Token 用量统计 ──
total_input_tokens = 0
total_output_tokens = 0


def rollback_messages(messages: list) -> None:
    """回滚 messages 末尾本轮未完成的消息。
    从末尾往前 pop,直到遇到一条"完整收尾"的 assistant 回复(不含 tool_use)为止,
    避免残留没有配对 tool_result 的 tool_use 导致 API 报错。"""
    while messages:
        last = messages[-1]
        if last["role"] == "user":
            messages.pop()
        elif last["role"] == "assistant":
            content = last["content"]
            # 内容是 model_dump 后的 dict 列表,所以用 b.get 而不是 getattr
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            ):
                messages.pop()
            else:
                break
        else:
            break

# PromptSession 只需创建一次,循环内复用(还能保留输入历史,按上下键可翻看)
session = PromptSession(key_bindings=kb)

while True:
    # 1. 拿用户输入
    try:
        user_input = session.prompt(">>> ", multiline=False)
    except KeyboardInterrupt:
        now = time.time()
        if now - last_interrupt < 2:
            sys.exit(0)
        last_interrupt = now
        console.print("[dim]再按一次 Ctrl+C 退出[/dim]")
        continue

    critic_rounds = 0
    # 2. 判断命令执行方法
    if user_input == "/exit":
        console.print(f"\n 本轮会话总计: input={total_input_tokens} tokens  output={total_output_tokens}  tokens")
        break
    elif user_input.startswith("/save"):
        name = user_input[6:].strip() or "default"
        session_mgr.save(messages, name)
        console.print(f"已保存到 [{name}]")
        continue

    elif user_input == "/list":
       files = sorted(
           session_mgr.dir.glob("*.json"),
           key = lambda f:f.stat().st_mtime,
           reverse = True,
       )
       if not files:
           console.print("（暂无已保存的会话）")
           continue
       choices = [f.stem for f in files] + ["取消"]
       choice = questionary.select("切换到哪个会话?",choices=choices).ask()

       if choice is None or choice == "取消":
           continue

       messages = session_mgr.load(choice)
       console.print(f"[dim]📂 已切换到 [{choice}],{len(messages)}条消息[/dim]")
       continue


    elif user_input.startswith("/load"):
        name = user_input[6:].strip()
        messages = session_mgr.load(name)
        console.print(f"已切换到 [{name}]，共 {len(messages)} 条消息")
        continue

    elif user_input == "/clear":
        # 只清内存,不覆盖磁盘上的旧会话;重置会话名,下次保存时自动生成新会话
        messages = []
        session_mgr.current_name = "default"
        session_mgr.current_path = session_mgr.dir / "default.json"
        console.print("会话已清空,新对话将保存为新会话")
        continue

    turn_in = 0
    turn_out = 0

    # 3. 把用户的话加到 messages
    messages.append({
        "role": "user",
        "content": user_input
    })

    try:
        while True:
            # 4. 调 API
            with client.messages.stream(
                    model="deepseek-v4-pro",
                    system=prompt,
                    max_tokens=8192,
                    tools=Tools,
                    messages=messages
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
                "content": [b.model_dump(mode="json") for b in response.content]
            })

            # 7. 没工具要调,跳出内层循环回到等用户输入
            if response.stop_reason == "end_turn":
                # 增加进入记忆
                session_mgr.save(messages)
                break

            # 8. 工具调用:统一交给 run_tool 分发
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    console.print(f"[dim]→ {block.name}({str(block.input)[:60]})[/dim]")
                    if block.name == "run_cmd":
                        cmd = block.input['cmd']
                        # 已批准过的命令直接放行,不再询问
                        if cmd not in approve_cmds:
                            confirm = input(f"是否执行命令 `{cmd}` ?(y/n/a): ").strip().lower()
                            if confirm == "a":
                                approve_cmds.add(cmd)
                            elif confirm == "n":
                                console.print("用户取消命令")
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": "用户拒绝命令"
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
                    session_mgr.save(messages)

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
    except KeyboardInterrupt:
        # 生成中被打断 → 清理 messages 末尾,continue 到外层
        now = time.time()
        if now - last_interrupt < 2:
            sys.exit(0)
        last_interrupt = now
        console.print("\n[dim]已中断生成,再按一次 Ctrl+C 退出[/dim]")
        # 回滚本轮未完成的消息(包括打断在工具循环中间残留的 tool_use)
        rollback_messages(messages)
        continue
    except Exception as e:
        # 网络/API 异常(连接断开、超时等)→ 清理后回到等输入
        console.print(f"\n[red]网络/API 异常: {type(e).__name__}: {e}[/red]")
        console.print("[dim]已回滚本轮输入,可重新发送[/dim]")
        rollback_messages(messages)
        continue

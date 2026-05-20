import subprocess
from tavily import TavilyClient
import json
from rich.console import Console
import time
from concurrent.futures import ThreadPoolExecutor
import time


def slow_task(name):
    return f"{name} done"


with ThreadPoolExecutor(max_workers=3) as pool:
    # 1. 提交 3 个任务，立刻返回 Future，不阻塞
    f1 = pool.submit(slow_task,"A")
    f2 = pool.submit(slow_task, "B")
    f3 = pool.submit(slow_task, "C")

    # 2. 拿结果，.result() 会阻塞直到完成
    print(f1.result())  # "A done"
    print(f2.result())  # "B done"
    print(f3.result())  # "C done"
# def run_cmd(cmd: str) -> tuple:
#     try:
#         result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
#         return result.stdout, result.stderr, result.returncode
#     except Exception as e:
#         return f"运行失败: {e}", "", -1
#
# stdout, stderr, code = run_cmd("java --version")
# print(f"stdout: {stdout}")
# print(f"stderr: {stderr}")
# print(f"returncode: {code}")


# response = client.search("明天南充天气怎么样")
# results = response["results"]
# print(results[0]['content'])

# example = ["苹果","梨子"]
# for i,r in enumerate(example,1):
#     print(f"{i},{r}")


# response = client.extract(
#     urls=["https://www.aibase.com/zh"]
# )
# print(json.dumps(response,indent=2,ensure_ascii=False))

# console = Console()
# with console.status("[dim]Thinking...[/dim]",spinner="dots"):
#     time.sleep(10)
#     console.print("hello")
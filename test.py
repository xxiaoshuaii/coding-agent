import subprocess
from tavily import TavilyClient
import json

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
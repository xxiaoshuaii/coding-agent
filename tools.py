import os
import subprocess
import time
import uuid
from pathlib import Path
from tavily import TavilyClient
import json
import requests
import dashscope
from dashscope import ImageSynthesis

prompt = """你是运行在用户本地 Windows 终端里的编程助手。

  你可以使用以下工具:read_file、write_file、list_files、run_cmd、grep、web_search、edit_file、generate_image

  generate_image 使用规则:
  - 写 HTML/Markdown/幻灯片时,如果配图能让效果更好,主动调用 generate_image 生成插图
  - 一次只生成一张图,需要多张就分多次调
  - 返回的路径是相对路径(./images/xxx.png),直接写到 <img src="..."> 里即可
  - prompt 要具体,描述画面内容、风格、构图,不要写"一张关于 X 的图"这种空话

  工作原则:
  1. 调用 web_search 前,请务必先使用 run_cmd 核对今日的日期,确保消息及时性
  2. 不确定路径时,先用 list_files 探查,而不是猜
  3. 调用 run_cmd 前,用一句话说明这条命令的目的
  4. 一次回复中,最多调用一个 write_file 或 run_cmd
  5. 回复简洁,优先中文,代码用 markdown 代码块
  6. 修改任何文件前,先用 read_file 确认当前内容

   大任务处理规则:

  7. 判断任务规模:如果预计需要新建 ≥2 个文件,或单个文件预计超过 200 行,
     这就是"大任务",必须走下面的"先计划后动手"流程。
     只改几行、改一个小文件这种属于小任务,直接动手即可。

  8. 大任务的"先计划"阶段:
     - 不要立刻调用 write_file
     - 用纯文字回复列出:
       * 要创建的文件清单(每个文件的路径、职责、预计行数)
       * 文件之间的依赖关系(哪个先写、哪个后写)
     - 然后停下来,等用户回复"好"/"继续"/"开始"等确认词后再动手
     - 用户提出修改意见的,按意见调整计划再确认,不要自作主张开始写

  9. 大任务的"动手"阶段(用户确认后):
     - 最多一次性执行三次 write_file 工具
     - 每写完一个文件,用一两句话报告:刚写了什么、接下来写哪个
     - 直到全部文件写完才结束本轮

单文件体积约束:

  10. 任何一次 write_file 的 content,目标控制在 6000 字符以内(约 200 行)。
      超出就要拆分:
      - HTML 项目拆成 index.html + style.css + app.js,而不是塞进一个大 HTML
      - Vue/React 按组件拆成独立文件
      - 后端代码按模块/路由拆文件
      宁可多几个文件,不要单个文件过大。

  遇到不清楚的需求,先问清楚再动手,不要猜测用户意图。"""


"跳过目录"
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv", "node_modules", ".idea"}

def read_file(path: str,offset:int = 0,limit: int = None) -> str:
    """真的去读文件,返回内容字符串。
    offset 起始页,
    limit 最后一页"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            total = len(lines)
        if limit is None:
            selected = lines[offset:]
        else:
            selected = lines[offset:limit]
        content = "".join(selected)
        if offset == 0 and limit is None:
            return content
        else:
            end = offset + len(selected)
            header = f"(显示第 {offset + 1}-{end} 行,共 {total} 行)\n"
            return header + content
    except Exception as e:
        return f"读取失败: {e}"


def write_file(path: str, content: str) -> str:
    """真的去写文件,返回结果字符串。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "写入成功"
    except Exception as e:
        return f"写入失败: {e}"


def list_files(path: str) -> str:
    """真的去列出文件,返回结果字符串。"""
    try:
        folder = os.listdir(path)
        return "\n".join(folder) if folder else "空文件夹"
    except Exception as e:
        return f"列出失败: {e}"

def run_cmd(cmd: str) -> str:
    """真的去运行命令,返回结果字符串。"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,timeout=30)
        return f"""exit code: {result.returncode}
                    stdout:
                    {result.stdout}
                    stderr:
                    {result.stderr}"""
    except subprocess.TimeoutExpired:
        return "运行超时"
    except Exception as e:
        return f"""运行失败: {e}", f"运行失败: {e},"""


def edit_file(path: str,old: str,new: str,replace_all: bool = False) -> str:
    """真的去修改文件,返回结果字符串。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            count = content.count(old)
            if count == 0:
                return "未找到错误"
            elif count == 1:
                content = content.replace(old, new)
            else:
                if replace_all:
                    content = content.replace(old, new)
                else:
                    return f"找到{count}个匹配,请选择是否替换所有匹配"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "修改成功"
    except Exception as e:
        return f"修改失败: {e}"

def grep(pattern: str, path: str, glob: str = "*") -> str:
    results = []
    max_results = 100
    truncated = False
    for file in Path(path).rglob(glob):
        if any(part in SKIP_DIRS for part in file.parts):
            continue
        if not file.is_file():
            continue
        try:
            with open(file, "r", encoding="utf-8") as f:
                content = f.readlines()
        except Exception:
            continue
        for i,line in enumerate(content,start=1):
            if pattern in line:
                if len(results) >= max_results:
                    truncated = True
                    break
                results.append(f"{file}:{i}:{line.rstrip()}")
        if truncated:
            break
    if not results:
        return "没有找到匹配"
    output = "\n".join(results)
    if truncated:
        output += f"\n\n(结果被截断,只显示前 {max_results} 条)"
    return output

def generate_image(prompt: str, size: str = "1024*1024") -> str:
    """调用通义万相文生图,保存到 ./images/,返回本地相对路径。"""
    try:
        dashscope.api_key = ""
        rsp = ImageSynthesis.call(
            model="wanx2.1-t2i-turbo",
            prompt=prompt,
            n=1,
            size=size,
        )
        if rsp.status_code != 200:
            return f"生成失败: code={rsp.code} message={rsp.message}"

        url = rsp.output.results[0].url
        os.makedirs("./images", exist_ok=True)
        filename = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        path = f"./images/{filename}"

        img_data = requests.get(url, timeout=30).content
        with open(path, "wb") as f:
            f.write(img_data)

        return f"图像已保存: {path} (尺寸: {size})"
    except Exception as e:
        return f"生成失败: {e}"


def web_search(query : str) ->str:
    try:
        client = TavilyClient(os.environ["TAVILY_API_KEY"])
        response = client.search(query)
        results = response["results"]
        lines = []
        for i,r in enumerate(results,1):
            lines.append(f"[{i}] {r['title']}")
            lines.append(f"URL:{r['url']}")
            lines.append(r['content'])
        return "\n".join(lines)
    except Exception as e:
        return f"错误信息:{e}"



# 给模型看的工具说明书(schema)
Tools = [
    {
        "name": "read_file",
        "description": "读取一个文件内容",
        "input_schema": {
            "type": "object",
            "properties": {
              "path":   {"type": "string",  "description": "文件路径"},
              "offset": {"type": "integer", "description": "可选,从第几行开始读(0 表示从头),用于跳过开头部分"},
              "limit":  {"type": "integer", "description": "可选,最多读多少行,用于限制返回长度"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "写入一个文件(会覆盖已有内容)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "填写文件路径"},
                "content": {"type": "string", "description": "填写内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "列出一个文件夹下的所有文件",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "填写文件夹路径"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_cmd",
        "description": "运行一个命令",
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "填写命令"}
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "edit_file",
        "description": "在文件中精确替换一段文本。old_string 必须在文件中唯一匹配,否则报错。修改前应先用 read_file 查看当前内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "填写文件夹路径"},
                "old": {"type": "string", "description": "填写内容"},
                "new": {"type": "string", "description": "填写内容"},
                "replace_all": {"type": "boolean", "description": "是否替换所有匹配,默认 false"}
            },
            "required": ["path", "old", "new","replace_all"]
        }
    },
    {
        "name": "grep",
        "description": "用户给出关键字,在文件中查找对应出现的位置。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":{"type" : "string","description": "需要匹配的对象"},
                "path": {"type": "string", "description": "填写文件夹路径"}

            },
            "required": ["pattern","path"]
        }
    },
    {
        "name": "generate_image",
        "description": "用通义万相生成一张图片,保存到 ./images/ 并返回本地相对路径。适合在写 HTML/幻灯片/Markdown 时配图。",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "图片内容的详细描述,越具体越好"},
                "size":   {"type": "string", "description": "图片尺寸,可选 1024*1024(默认正方形)、1280*720(横屏,适合幻灯片)、720*1280(竖屏)"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "web_search",
        "description": "用户给出搜索的问题,调用工具搜索有关内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":{"type" : "string","description": "需要搜索的问题"}

            },
            "required": ["query"]
        }
    },
]

# 工具名 -> 函数 的分发表
# Python 里函数是一等对象,可以直接当 value 存到 dict 里
# 取代 if/elif 长链:TOOL_FUNCS[name](**input)
TOOL_FUNCS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "run_cmd": run_cmd,
    "edit_file": edit_file,
    "grep": grep,
    "web_search" : web_search,
    "generate_image": generate_image,
}


def run_tool(name: str, tool_input: dict) -> str:
    """根据工具名分发到具体函数。tool_input 是 Claude 返回的参数 dict。"""
    func = TOOL_FUNCS.get(name)
    if func is None:
        return f"未知工具: {name}"
    return func(**tool_input)  # ** 把 dict 解包成关键字参数

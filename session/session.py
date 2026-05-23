import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import anthropic


class SessionManager:
    """管理会话的保存 / 加载 / 列表 / 切换"""
    def __init__(self, session_dir: str = "./sessions"):
        self.dir = Path(session_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.current_name = "default"
        self.current_path = self.dir / self.current_name

    # 保存每一次与大模型之间的对话
    def save(self, message: list, name: str | None = None) -> str:
        if name is None:
            # 当前会话还是 "default"(说明还没起过名),且有消息可用 →
            if self.current_name == "default" and message:
                first_user = None
                for m in message:
                    if m["role"] == "user":
                        first_user = m["content"]
                        break
                if first_user:
                    name = self._generate_name(first_user)
                    self.current_name = name
                else:
                    name = self.current_name
            else:
                name = self.current_name
            self.current_path = self.dir / f"{name}.json"
        data = {
            "name": name,
            "create_time": self._now(),
            "update_time": self._now(),
            "messages": message
        }
        if self.current_path.exists():
            with self.current_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                data["update_time"] = self._now()
                data["messages"] = message
        else:
            self.current_path.touch()
        with self.current_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return f"保存成功: {self.current_path}"

    # 加载对话
    def load(self, name: str | None = None) -> list:
        """
        name: 会话名（不带 .json），不传就加载最近一次使用的会话
        返回:  messages 列表（可直接赋值给 agent.py 的 messages）
        """
        if name:
            path = self.dir / f"{name}.json"
        else:
            # 找最近更新过的会话文件
            files = sorted(
                self.dir.glob("*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            path = files[0] if files else None

        if path is None or not path.exists():
            return []  # 没有任何历史会话，返回空列表

        self.current_name = path.stem  # 文件名去掉 .json
        self.current_path = path
        data = json.loads(path.read_text("utf-8"))
        return data.get("messages", [])

    # 列出对话记录
    def list_sessions(self) -> str:
        """返回格式化的会话列表，给终端显示用"""
        files = sorted(
            self.dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return "（暂无已保存的会话）"

        lines = []
        for f in files:
            data = json.loads(f.read_text("utf-8"))
            name = data.get("name", f.stem)
            updated = data.get("update_time", "未知")
            msg_count = len(data.get("messages", []))
            marker = " ← 当前" if f.stem == self.current_name else ""
            lines.append(f"  [{name}]  {msg_count} 条消息  最后更新: {updated}{marker}")
        return "\n".join(lines)

    def delete(self, name: str) -> str:
        path = self.dir / f"{name}.json"
        if not path.exists():
            return f"会话 [{name}] 不存在"
        path.unlink()
        if name == self.current_name:
            self.current_name = "default"
            self.current_path = self.dir / "default.json"
        return f"已删除会话 [{name}]"

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _generate_name(self, first_user_msg: str):
        client = anthropic.Anthropic(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ["DEEPSEEK_BASE_URL"],
        )
        resp = client.messages.create(
            model="deepseek-v4-flash",
            thinking={"type": "disabled"},
            max_tokens=10000,
            messages=[
                {
                    "role": "user",
                    "content":  f"用不超过10个字总结这段话作为对话标题,只返回标题本身,不要引号和标点:\n\n{first_user_msg}"
                }]
        )
        title = ""
        for block in resp.content:
            if block.type == "text":
                title = block.text.strip()
                break
        for ch in r'\/:*?"<>|':
            title = title.replace(ch, "")
        return title or self._now().replace(" ", "_").replace(":", "")








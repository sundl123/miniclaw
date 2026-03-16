#!/usr/bin/env python3
"""
基于 MiniMax API 的命令行 LLM 对话工具，支持 code-execution 工具与 .skills 技能目录。
使用方式: MINIMAX_API_KEY=your_key python3 chat.py
"""
import os
import sys
import json
import re
import subprocess
import requests

# 工作区根 = chat.py 所在目录（项目根）
WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(WORKSPACE_ROOT, ".skills")

# MiniMax API（api.minimaxi.com）
# 带 tools 时使用 OpenAI 兼容端点以支持 tool_calls
BASE_URL = "https://api.minimaxi.com"
CHAT_URL = f"{BASE_URL}/v1/text/chatcompletion_v2"
CHAT_URL_OPENAI = f"{BASE_URL}/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.5"


# ---------- 技能元数据扫描 ----------
def _parse_frontmatter(content: str) -> dict:
    """从 SKILL.md 内容中解析 YAML frontmatter，返回 name、description 等。"""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    block = match.group(1)
    data = {}
    for line in block.split("\n"):
        m = re.match(r"^(\w+):\s*(.*)$", line.strip())
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"')
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1].replace("\\'", "'")
            data[key] = val
    return data


def scan_skills_metadata(skills_dir: str = None) -> list[dict]:
    """扫描 .skills 目录，返回 [{"name": "...", "description": "..."}, ...]。"""
    skills_dir = skills_dir or SKILLS_DIR
    result = []
    if not os.path.isdir(skills_dir):
        return result
    for name in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, name)
        if not os.path.isdir(path):
            continue
        skill_md = os.path.join(path, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        meta = _parse_frontmatter(content)
        result.append({
            "name": meta.get("name") or name,
            "description": meta.get("description", "(无描述)"),
        })
    return result


def build_system_prompt(skill_metadata_list: list[dict]) -> str:
    """根据技能元数据列表拼接 system prompt。"""
    lines = [
        "你是助手，拥有一个 code_execution 工具，可以：执行 bash 命令、查看/创建/编辑工作区内的文件。",
        "",
        "## 技能（Skills）的访问方式",
        "技能存放在工作区根目录下的 .skills 目录中。",
        "每个技能对应一个子目录，例如 .skills/<skill_name>/。",
        "目录内必有 SKILL.md，描述该技能的用途与使用方式；可能还有 assets/ 等子目录存放模板或脚本。",
        "当你认为用户需求可能涉及某技能时，应先用 view_file 查看对应 .skills/<skill_name>/SKILL.md，再根据 SKILL.md 的说明决定是否执行 bash 或读写其他文件。",
        "",
        "## 当前可用技能列表（自动从 .skills 扫描）",
    ]
    if skill_metadata_list:
        for s in skill_metadata_list:
            lines.append(f"- {s['name']}: {s['description']}")
    else:
        lines.append("（暂无，可在 .skills 下添加技能目录及 SKILL.md）")
    return "\n".join(lines)


# ---------- Code Execution 工具 ----------
def _resolve_path(path: str) -> str:
    """将相对 path 解析为工作区内的绝对路径，禁止 .. 逃逸。"""
    path = path.lstrip("/")
    abs_path = os.path.normpath(os.path.join(WORKSPACE_ROOT, path))
    if not abs_path.startswith(WORKSPACE_ROOT):
        raise PermissionError(f"路径不允许超出工作区: {path}")
    return abs_path


def handle_code_execution(arguments: dict) -> str:
    """执行 code_execution 工具：run_bash / view_file / create_file / edit_file。"""
    action = (arguments.get("action") or "").strip()
    if not action:
        return json.dumps({"error": "缺少 action 参数"}, ensure_ascii=False)

    try:
        if action == "run_bash":
            cmd = arguments.get("command") or ""
            if not cmd:
                return json.dumps({"error": "run_bash 需要 command 参数"}, ensure_ascii=False)
            r = subprocess.run(
                ["bash", "-c", cmd],
                cwd=WORKSPACE_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            if r.returncode != 0:
                return f"exit code: {r.returncode}\nstdout:\n{out}\nstderr:\n{err}"
            return out or "(无输出)"

        if action == "view_file":
            path = arguments.get("path") or ""
            if not path:
                return json.dumps({"error": "view_file 需要 path 参数"}, ensure_ascii=False)
            abs_path = _resolve_path(path)
            if not os.path.isfile(abs_path):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        if action == "create_file":
            path = arguments.get("path") or ""
            content = arguments.get("content") or ""
            if not path:
                return json.dumps({"error": "create_file 需要 path 参数"}, ensure_ascii=False)
            abs_path = _resolve_path(path)
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Created file: {path}"

        if action == "edit_file":
            path = arguments.get("path") or ""
            content = arguments.get("content") or ""
            mode = (arguments.get("mode") or "replace").strip().lower()
            if not path:
                return json.dumps({"error": "edit_file 需要 path 参数"}, ensure_ascii=False)
            abs_path = _resolve_path(path)
            if mode == "append":
                with open(abs_path, "a", encoding="utf-8") as f:
                    f.write(content)
                return f"Appended to: {path}"
            if mode == "insert":
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    old = f.read()
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(content + old)
                return f"Inserted at beginning of: {path}"
            # replace
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Replaced content of: {path}"

        return json.dumps({"error": f"未知 action: {action}"}, ensure_ascii=False)
    except PermissionError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "run_bash 执行超时（60s）"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_code_execution_tool_schema() -> dict:
    """返回 MiniMax/OpenAI 风格的 code_execution 工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": "code_execution",
            "description": "Execute bash commands or read/write files in the workspace. Use view_file to read .skills/<name>/SKILL.md for skill instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["run_bash", "view_file", "create_file", "edit_file"],
                        "description": "Operation: run_bash, view_file, create_file, edit_file",
                    },
                    "command": {
                        "type": "string",
                        "description": "Bash command (required when action=run_bash)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative path under workspace (required for view_file, create_file, edit_file)",
                    },
                    "content": {
                        "type": "string",
                        "description": "File content (required for create_file, edit_file)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append", "insert"],
                        "description": "For edit_file: replace (default), append, insert",
                    },
                },
                "required": ["action"],
            },
        },
    }


def get_api_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        print("错误: 请设置环境变量 MINIMAX_API_KEY", file=sys.stderr)
        print("示例: export MINIMAX_API_KEY=your_api_key", file=sys.stderr)
        sys.exit(1)
    return key


def chat(api_key: str, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> str:
    """调用 MiniMax 对话 API，返回助手回复文本（无 tool 时）。"""
    msg, _ = chat_raw(api_key, messages, model=model, **kwargs)
    return (msg.get("content") or "").strip()


def chat_raw(api_key: str, messages: list[dict], model: str = DEFAULT_MODEL, **kwargs) -> tuple[dict, dict]:
    """调用 MiniMax 对话 API，返回完整 message 与整份 data（含 tool_calls、reasoning_details）。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        **kwargs,
    }
    # 带 tools 时使用 OpenAI 兼容端点并启用 reasoning_split
    use_tools = bool(kwargs.get("tools"))
    url = CHAT_URL_OPENAI if use_tools else CHAT_URL
    if use_tools and "extra_body" not in kwargs:
        payload["extra_body"] = {"reasoning_split": True}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        msg = base.get("status_msg", "Unknown error")
        raise RuntimeError(f"MiniMax API 错误: {msg} (code={base.get('status_code')})")

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("API 返回无内容")

    message = choices[0].get("message", {})
    return message, data


def run_turn_with_tools(
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    *,
    print_reasoning: bool = True,
) -> tuple[str, list[dict]]:
    """带 tool 的对话循环：请求 → 若有 tool_calls 则执行并追加消息 → 再请求，直到无 tool_calls。返回最终文本与更新后的 messages。"""
    while True:
        message, _ = chat_raw(api_key, messages, model=model, tools=tools, tool_choice="auto")
        reasoning_details = message.get("reasoning_details") or []
        if print_reasoning and reasoning_details:
            for d in reasoning_details:
                if isinstance(d, dict) and d.get("text"):
                    print(f"\n💭 Thinking:\n{d['text']}\n")
        tool_calls = message.get("tool_calls") or []
        # 将完整 assistant 消息追加到历史（含 reasoning_details 以保持思维链）
        assistant_msg = {"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls}
        if message.get("reasoning_details"):
            assistant_msg["reasoning_details"] = message["reasoning_details"]
        messages.append(assistant_msg)
        if not tool_calls:
            return (message.get("content") or "").strip(), messages
        # 执行每个 tool_call 并追加 tool 结果
        for tc in tool_calls:
            tid = tc.get("id") or tc.get("tool_use_id")
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            args_str = fn.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}
            result = handle_code_execution(args) if name == "code_execution" else json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
            # MiniMax 可能接受 role "tool" 或 role "user" + content [tool_result]，此处用 role "tool" 常见格式
            messages.append({"role": "tool", "tool_call_id": tid, "content": result})


def main():
    api_key = get_api_key()
    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
    # 自动扫描 .skills 并渲染技能列表到 system prompt
    skill_meta = scan_skills_metadata()
    system_prompt = build_system_prompt(skill_meta)
    # 若用户设置了 MINIMAX_SYSTEM，可追加（可选）
    extra_system = os.environ.get("MINIMAX_SYSTEM", "").strip()
    if extra_system:
        system_prompt = system_prompt + "\n\n" + extra_system
    tools = [get_code_execution_tool_schema()]

    messages: list[dict] = []
    messages.append({"role": "system", "content": system_prompt})

    print("MiniMax 命令行对话 + Code Execution + .skills (输入 /quit 退出, /clear 清空历史, /model 查看当前模型)")
    print("-" * 50)

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not user_input:
            continue

        if user_input in ("/quit", "/exit", "/q"):
            print("再见。")
            break
        if user_input == "/clear":
            messages = [{"role": "system", "content": system_prompt}]
            print("[已清空对话历史]")
            continue
        if user_input == "/model":
            print(f"当前模型: {model}")
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            reply, messages = run_turn_with_tools(
                api_key, model, messages, tools, print_reasoning=True
            )
            print(f"\nMiniMax: {reply}\n")
        except requests.RequestException as e:
            print(f"\n[网络/请求错误] {e}\n", file=sys.stderr)
            messages.pop()
        except RuntimeError as e:
            print(f"\n[API 错误] {e}\n", file=sys.stderr)
            messages.pop()


if __name__ == "__main__":
    main()

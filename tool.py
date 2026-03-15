import anthropic
import json
import requests
from typing import List, Dict, Any, Optional, Callable

# ============ MiniMax 客户端 ============
class MiniMaxClient:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "MiniMax-M2.5"
    
    def chat(self, messages: List[Dict], 
             tools: Optional[List[Dict]] = None,
             system: str = "You are a helpful assistant.",
             **kwargs) -> Dict:
        """调用 API"""
        resp = self.client.messages.create(
            model=self.model,
            system=system,
            messages=messages,
            tools=tools or [],
            max_tokens=4096,
            **kwargs
        )
        return resp

# ============ Skill 定义 ============
class Skill:
    def __init__(self, name: str, description: str, 
                 instructions: str = "", tools: List[Dict] = None):
        self.name = name
        self.description = description  # 触发条件
        self.instructions = instructions
        self.tools = tools or []
    
    def to_tools(self) -> List[Dict]:
        """转换为 MiniMax tools 格式"""
        return self.tools
    
    def get_system_prompt(self) -> str:
        return f"""You are a {self.name} assistant.

{self.instructions}

Available tools:
{json.dumps(self.tools, indent=2, ensure_ascii=False)}"""

# ============ Skill 注册中心 ============
class SkillRegistry:
    def __init__(self, client: MiniMaxClient):
        self.client = client
        self.skills: Dict[str, Skill] = {}
    
    def register(self, skill: Skill):
        self.skills[skill.name] = skill
    
    def match(self, user_input: str) -> Optional[Skill]:
        """用简单关键词匹配或 LLM 判断触发哪个 Skill"""
        user_lower = user_input.lower()
        
        # 简单规则匹配
        for name, skill in self.skills.items():
            if any(kw in user_lower for kw in skill.description.lower().split()):
                return skill
        
        # 可扩展：用 LLM 判断
        return None

# ============ 工具执行器 ============
class ToolExecutor:
    def __init__(self):
        self.handlers: Dict[str, Callable] = {}
    
    def register(self, name: str, handler: Callable):
        self.handlers[name] = handler
    
    def execute(self, tool_name: str, tool_input: Dict) -> Any:
        if tool_name in self.handlers:
            return self.handlers[tool_name](tool_input)
        return {"error": f"Unknown tool: {tool_name}"}

# ============ 完整 Agent 循环 ============
class SkillAgent:
    def __init__(self, client: MiniMaxClient, registry: SkillRegistry, executor: ToolExecutor):
        self.client = client
        self.registry = registry
        self.executor = executor
        self.messages: List[Dict] = []
    
    def set_system(self, skill: Skill):
        """设置 Skill 的 system prompt"""
        self.messages = [{
            "role": "system",
            "content": skill.get_system_prompt()
        }]
    
    def add_user(self, content: str):
        self.messages.append({
            "role": "user", 
            "content": [{"type": "text", "text": content}]
        })
    
    def step(self) -> Dict:
        """执行一步（可能是文本回复或工具调用）"""
        resp = self.client.chat(self.messages)
        
        # 提取 content blocks
        blocks = []
        tool_calls = []
        
        for block in resp.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_calls.append({
                    "name": block.name,
                    "input": block.input,
                    "id": block.id
                })
            elif block.type == "thinking":
                # 可选：记录思考过程
                pass
        
        # 添加助手回复到历史
        self.messages.append({
            "role": "assistant",
            "content": blocks + [{"type": "tool_use", "name": t["name"], "input": t["input"], "id": t["id"]} 
                               for t in tool_calls] if tool_calls else blocks
        })
        
        return {"blocks": blocks, "tool_calls": tool_calls}
    
    def execute_tools(self, tool_calls: List[Dict]) -> List[Dict]:
        """执行工具调用并返回结果"""
        results = []
        for tc in tool_calls:
            result = self.executor.execute(tc["name"], tc["input"])
            results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False)
            })
            
            # 添加工具结果到历史
            self.messages.append({
                "role": "user",
                "content": [results[-1]]
            })
        return results
    
    def run(self, user_input: str, skill: Skill, max_turns: int = 5):
        """完整运行流程"""
        self.set_system(skill)
        self.add_user(user_input)
        
        for turn in range(max_turns):
            result = self.step()
            
            if result["tool_calls"]:
                # 执行工具
                self.execute_tools(result["tool_calls"])
            else:
                # 返回文本回复
                return result["blocks"][0]["text"] if result["blocks"] else ""
        
        return "Max turns reached"

# ============ 示例：定义 Skill + Tools ============
def main():
    API_KEY = "your-minimax-api-key"
    client = MiniMaxClient(API_KEY)
    
    # 1. 创建工具
    def get_weather(input_dict):
        return {"temp": 22, "condition": "sunny", "city": input_dict.get("city", "深圳")}
    
    def calc(input_dict):
        expr = input_dict.get("expression", "0")
        try:
            result = eval(expr)
            return {"result": result}
        except:
            return {"error": "Invalid expression"}
    
    # 2. 定义 Skill
    weather_skill = Skill(
        name="weather-assistant",
        description="天气查询助手 - 当用户询问天气、温度、预报时使用",
        instructions="你是一个专业的天气助手。使用工具来获取天气信息。",
        tools=[
            {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"}
                    },
                    "required": ["city"]
                }
            },
            {
                "name": "calculator",
                "description": "数学计算器",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "数学表达式"}
                    },
                    "required": ["expression"]
                }
            }
        ]
    )
    
    # 3. 注册
    registry = SkillRegistry(client)
    registry.register(weather_skill)
    
    executor = ToolExecutor()
    executor.register("get_weather", get_weather)
    executor.register("calculator", calc)
    
    # 4. 运行
    agent = SkillAgent(client, registry, executor)
    matched = registry.match("深圳今天天气怎么样?")
    
    if matched:
        response = agent.run("深圳今天天气怎么样?", matched)
        print(f"回复: {response}")

if __name__ == "__main__":
    main()
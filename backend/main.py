import asyncio
import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4
import httpx
import edge_tts
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

BASE_DIR = Path(__file__).resolve().parent.parent #  定义基础目录路径，使用当前文件的上级目录作为基准 Path(__file__) 获取当前文件的路径 .resolve() 将路径解析为绝对路径 .parent 获取父目录 .parent 再次获取父目录，即当前文件的上两级目录
load_dotenv(BASE_DIR / ".env") #  加载环境变量配置文件，从项目根目录下的.env文件中读取环境变量 load_dotenv函数用于从.env文件加载环境变量到系统环境变量中 BASE_DIR / ".env" 表示项目根目录下的.env文件路径

app = FastAPI(title="干饭辩论赛 - Sprint 4") #  创建FastAPI应用实例，并设置API的标题为"干饭辩论赛 - Sprint 4"


class RecommendRequest(BaseModel):

    """
    推荐请求模型类，用于接收用户推荐请求的相关参数。
    继承自BaseModel，提供数据验证和序列化功能。
    """
    taste: str = Field(min_length=1, max_length=100)  # 用户口味偏好，长度限制在1-100字符之间
    budget: int = Field(ge=1, le=500)  # 用户预算范围，限制在1-500之间
    weather: str = Field(min_length=1, max_length=50)  # 天气情况，长度限制在1-50字符之间
    restrictions: str = Field(default="无", max_length=200)  # 饮食限制，默认值为"无"，最大长度200字符
    note: str = Field(default="", max_length=300)  # 备注信息，默认值为空字符串，最大长度300字符


class RecommendResponse(BaseModel):

    """
    推荐响应模型类，用于封装推荐菜品的相关信息

    继承自BaseModel，通常用于数据验证和序列化
    """
    dish: str    # 推荐的菜品名称
    reason: str  # 推荐该菜品的理由
    tip: str     # 关于该菜品的小贴士或建议
class DebateRequest(RecommendRequest):
    """
    辩论请求类，继承自RecommendRequest，用于设置辩论相关的参数和验证逻辑。
    包含辩论轮数设置、双方辩手信息、立场声明、角色设定以及菜单内容等字段。
    """
    # 辩论轮数设置，默认为3轮，范围限制在1-5轮之间
    rounds: int = Field(default=3, ge=1, le=5)
    # 辣方辩手名称，默认为"辣子哥"，最大长度限制为30个字符
    spicy_name: str = Field(default="辣子哥", max_length=30)
    # 健康方辩手名称，默认为"清补凉"，最大长度限制为30个字符
    healthy_name: str = Field(default="清补凉", max_length=30)
    # 辣方立场声明，默认为"spicy"，最大长度限制为100个字符
    spicy_stance: str = Field(default="spicy", max_length=100)
    # 健康方立场声明，默认为"healthy"，最大长度限制为100个字符
    healthy_stance: str = Field(default="healthy", max_length=100)
    # 辣方角色设定，默认为"火爆川菜大厨，无辣不欢"，最大长度限制为200个字符
    spicy_persona: str = Field(default="火爆川菜大厨，无辣不欢", max_length=200)
    # 健康方角色设定，默认为"温和粤菜师傅，讲究本味和均衡"，最大长度限制为200个字符
    healthy_persona: str = Field(default="温和粤菜师傅，讲究本味和均衡", max_length=200)
    # 菜单内容，默认为空字符串，最大长度限制为1000个字符
    menu: str = Field(default="", max_length=50000)

    # 模型验证器，在模型创建后自动执行，用于应用默认值
    @model_validator(mode="after")
    def apply_defaults(self) -> "DebateRequest":
        # 定义默认值字典
        defaults = {
            "spicy_stance": "spicy",
            "healthy_stance": "healthy",
            "spicy_persona": "火爆川菜大厨，无辣不欢",
            "healthy_persona": "温和粤菜师傅，讲究本味和均衡",
            "menu": "",
            "note": "",
        }
        # 遍历默认值字典，检查并应用默认值
        for field, default in defaults.items():
            if not getattr(self, field).strip():
                setattr(self, field, default)
        return self
class Speech(BaseModel):

    # Speech类，用于表示一次演讲的模型，继承自BaseModel
    round: int  # 轮次，表示这是第几轮的演讲
    chef: str  # 厨师，表示演讲者的名字
    recommend: str  # 推荐，表示厨师推荐的内容
    reason: str  # 理由，表示推荐的理由
    score: int = Field(ge=0, le=100)  # 分数，表示演讲的得分，范围在0到100之间
    stance: str  # 立场，表示演讲者的立场
class DebateReport(BaseModel):

    """
    辩论报告模型类，用于存储辩论比赛的结果和相关信息。
    继承自BaseModel，假设是一个基础模型类，提供了一些基本功能。
    """
    winner: str  # 获胜方的名称，字符串类型
    dish: str    # 辩论主题或菜品名称，字符串类型
    score: dict[str, int]  # 得分情况，键为字符串类型，值为整型，存储各参赛方的得分
    summary: str  # 辩论总结，字符串类型，记录辩论的主要内容和结论
    barrage: str  # 弹幕内容，字符串类型，可能存储观众或观众的评论
class DebateSession(BaseModel):

    """
    辩论会话模型类，用于存储和管理辩论会话的相关信息。
    继承自BaseModel，提供了数据验证和序列化功能。
    """
    id: str  # 辩论会话的唯一标识符
    status: str = "PENDING"  # 辩论会话的状态，默认值为"PENDING"（待处理）
    request: DebateRequest  # 辩论请求对象，包含辩论的详细信息
    history: list[Speech] = Field(default_factory=list)  # 辩论发言历史记录列表，默认为空列表
    report: DebateReport | None = None  # 辩论报告，可选字段，默认为None
    error: str | None = None  # 错误信息，可选字段，默认为None，用于存储可能出现的错误描述
class FavoriteRequest(BaseModel):

    """
    收藏请求的数据模型类
    继承自BaseModel，用于验证和序列化请求数据
    """
    debate_id: str  # 辩论ID，必需的字符串类型字段
    dish: str = Field(min_length=1, max_length=100)  # 菜品名称，必需字符串，长度限制在1-100字符之间
    note: str = Field(default="", max_length=300)  # 备注，可选字符串，默认为空字符串，最大长度300字符

sessions: dict[str, DebateSession] = {} #  创建一个字典，用于存储辩论会话，键为字符串类型，值为DebateSession类型
DB_FILE = BASE_DIR / "ganfan.sqlite3" #  定义数据库文件的路径，使用BASE_DIR与"ganfan.sqlite3"拼接
stream_locks: dict[str, asyncio.Lock] = {} #  创建一个字典，用于存储流锁，键为字符串类型，值为异步锁类型

def _db() -> sqlite3.Connection:

    """
    创建并返回一个SQLite数据库连接，设置行工厂为sqlite3.Row以支持通过列名访问数据

    返回:
        sqlite3.Connection: 配置好的SQLite数据库连接对象
    """
    connection = sqlite3.connect(DB_FILE)  # 连接到指定的SQLite数据库文件
    connection.row_factory = sqlite3.Row
    return connection

def _init_db() -> None:
    """
    初始化数据库，创建必要的表结构
    如果表已存在，则不会重复创建
    """
    with _db() as connection:
        # 创建辩论表(debates)
        # 包含字段：id(主键，文本类型), data(文本，非空), status(文本，非空), updated_at(文本，非空)
        connection.execute("CREATE TABLE IF NOT EXISTS debates (id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL)")
        # 创建收藏表(favorites)
        # 包含字段：id(主键，自增整数), debate_id(文本，非空), dish(文本，非空),
        # note(文本，非空，默认值为空字符串), created_at(文本，非空)
        connection.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, debate_id TEXT NOT NULL, dish TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
        # 提交数据库事务，确保上述表创建操作被持久化
        connection.commit()

def _save_session(session: DebateSession) -> None:
    # 获取当前UTC时间并转换为ISO格式字符串
    now = datetime.now(timezone.utc).isoformat()
    # 使用数据库连接上下文管理器
    with _db() as connection:
        connection.execute("INSERT INTO debates(id, data, status, updated_at) VALUES (:id, :data, :status, :updated_at) ON CONFLICT(id) DO UPDATE SET data=excluded.data, status=excluded.status, updated_at=excluded.updated_at", {"id": session.id, "data": json.dumps(session.model_dump(), ensure_ascii=False), "status": session.status, "updated_at": now})
        connection.commit()

def _load_sessions() -> None:

    """
    加载所有辩论会话，从数据库和可能的旧文件中恢复数据。
    首先尝试从数据库加载，如果数据库为空则尝试从旧版JSON文件加载。
    """
    _init_db()  # 初始化数据库连接
    with _db() as connection:
        rows = connection.execute("SELECT data FROM debates ORDER BY updated_at DESC").fetchall()
    for row in rows:
        try:
            session = DebateSession.model_validate(json.loads(row["data"]))
            sessions[session.id] = session
            stream_locks[session.id] = asyncio.Lock()
        except (ValueError, TypeError):
            continue
    legacy_file = BASE_DIR / "debates.json"
    if legacy_file.exists() and not sessions:
        try:
            legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
            for value in legacy.values():
                session = DebateSession.model_validate(value)
                sessions[session.id] = session
                stream_locks[session.id] = asyncio.Lock()
                _save_session(session)
        except (OSError, ValueError, TypeError):
            pass
_load_sessions()

@app.get("/")
# 异步函数，用于处理前端首页请求
# 返回前端首页的HTML文件
async def index() -> FileResponse:
    # 使用FileResponse返回前端首页的HTML文件
    # 文件路径为BASE_DIR目录下的frontend/index.html
    return FileResponse(BASE_DIR / "frontend" / "index.html")

@app.post("/api/menu/upload") #  定义一个路由处理函数，用于处理菜单文件上传的POST请求
async def upload_menu(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = (file.filename or "").lower() #  获取文件名并转换为小写，如果文件名为空则使用空字符串
    if not filename.endswith((".csv", ".xlsx")): #  检查文件扩展名是否为.csv或.xlsx
        raise HTTPException(status_code=400, detail="只支持 CSV 或 XLSX 菜单文件。") #  如果文件类型不支持，抛出400错误
    content = await file.read() #  读取文件内容
    if len(content) > 5 * 1024 * 1024: #  检查文件大小是否超过5MB
        raise HTTPException(status_code=413, detail="菜单文件不能超过 5MB。")
    try:
        if filename.endswith(".csv"):
            rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")))) #  如果是CSV文件，使用csv模块读取内容
        else:
            from openpyxl import load_workbook #  如果不是CSV文件（假设是Excel文件），使用openpyxl库读取
            values = list(load_workbook(BytesIO(content), read_only=True, data_only=True).active.values) #  读取Excel文件的活动工作表，只读模式，且获取实际值而非公式
            headers = [str(value or "").strip() for value in values[0]] if values else [] #  提取表头，去除空值并转换为字符串
            rows = [dict(zip(headers, row)) for row in values[1:]] #  将每行数据与表头组合成字典
        items = []
        for row in rows: #  处理每一行数据
            clean = {str(key).strip(): str(value).strip() for key, value in row.items() if key and value not in (None, "")} #  清理数据：去除键和值的空格，过滤掉空键和空值
            if clean: #  如果清理后的数据不为空，则格式化为字符串并添加到items列表
                items.append("；".join(f"{key}：{value}" for key, value in clean.items()))
        return {"filename": file.filename, "count": len(items), "menu": "\n".join(items)} #  返回文件名、项目数量和格式化后的菜单内容
    except (UnicodeDecodeError, ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail="菜单文件格式无法解析，请检查首行是否为列名。") from error #  如果发生解析错误，抛出HTTP异常
@app.get("/api/tts") #  定义一个GET路由，用于文本转语音API
async def text_to_speech(text: str, voice: str = "zh-CN-YunxiNeural") -> StreamingResponse:
    if not text.strip() or len(text) > 500:
        raise HTTPException(status_code=400, detail="语音文本不能为空且不能超过 500 字。") #  当语音文本为空或超过500字时，抛出400错误
    if voice not in {"zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural"}: #  检查语音角色是否在支持的角色列表中
        raise HTTPException(status_code=400, detail="不支持的语音角色。") #  如果语音角色不支持，抛出400错误
    try:
        communicate = edge_tts.Communicate(text.strip(), voice) #  创建edge_tts的通信对象，使用传入的文本和语音角色
        audio = bytearray() #  初始化字节数组，用于存储音频数据
        async for chunk in communicate.stream(): #  异步遍历音频流数据
            if chunk["type"] == "audio": #  如果是音频数据块，则将其添加到音频字节数组中
                audio.extend(chunk["data"])
        return StreamingResponse(iter([bytes(audio)]), media_type="audio/mpeg", headers={"Cache-Control": "no-store"}) #  返回音频流响应，设置媒体类型为mpeg音频，并禁用缓存
    except Exception as error:
        raise HTTPException(status_code=502, detail="语音生成失败，请稍后重试。") from error #  如果语音生成过程中发生异常，抛出502错误


@app.post("/api/recommend", response_model=RecommendResponse)
async def recommend(request: RecommendRequest) -> RecommendResponse:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 SILICONFLOW_API_KEY，请在 .env 中设置。")

    prompt = f'''你是川菜大厨"辣子哥"，性格直爽热情，擅长根据用户情况推荐一道合适的菜。
用户口味：{request.taste}
预算：{request.budget} 元
天气：{request.weather}
忌口或过敏：{request.restrictions}
补充：{request.note or '无'}

必须优先遵守忌口与过敏要求。只推荐一道现实中常见、预算合理的菜品。
只输出 JSON，不要 Markdown 或额外文字：
{{"dish":"菜名","reason":"不超过60字的推荐理由","tip":"不超过40字的点餐小建议"}}'''

    payload = {
        "model": os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        "messages": [
            {"role": "system", "content": "你必须返回有效 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.siliconflow.cn/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
            )
            response.raise_for_status() #  检查HTTP响应状态码，如果请求失败（状态码不是2xx）则抛出异常
            # ✅ 在 with 块内解析响应
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return RecommendResponse.model_validate(json.loads(content))
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="请求超时，请稍后重试。")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"API 返回错误: {e.response.status_code}")
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=502, detail="推荐服务暂时不可用，请稍后重试。") from error

def _history_text(history: list[Speech]) -> str:
    return "暂无发言。" if not history else "\\n".join(f"第{s.round}轮 {s.chef}：{s.recommend}；{s.reason}" for s in history)

def _menu_candidates(menu: str) -> list[str]:
    candidates: list[str] = []
    for line in menu.replace("\\r", "").split("\\n"): #  遍历菜单文本，将回车符替换后按换行符分割成多行
        line = line.strip() #  去除每行的首尾空白字符
        if not line: #  如果行为空，则跳过当前循环
            continue
        match = re.search(r"菜品：([^；,，]+)", line) #  使用正则表达式搜索以"菜品："开头的内容，捕获非分号、非逗号后的所有字符
        if match: #  如果找到匹配项，将匹配到的菜品名称添加到候选列表中
            candidates.append(match.group(1).strip()) #  将匹配到的第一个组的内容去除首尾空格后添加到候选列表中 使用continue跳过当前循环的剩余部分
            continue
        for item in re.split(r"[,，;；]", line): #  使用正则表达式按逗号、分号（包括全角和半角）分割当前行
            item = item.strip() #  去除分割后每个元素的首尾空格
            if item and not item.startswith(("分类：", "价格：", "辣度：", "主要食材：")): #  如果元素不为空且不以"分类："、"价格："、"辣度："、"主要食材："开头
                candidates.append(item.split("：", 1)[-1].strip()) #  将元素按第一个冒号分割，取最后一部分并去除首尾空格后添加到候选列表
    return list(dict.fromkeys(candidates)) #  使用字典去重并转换为列表后返回

async def _call_chef(session: DebateSession, chef: str, stance: str, opponent: str, persona: str) -> Speech:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY，请在 .env 中设置。")
    r = session.request
    persona = persona.strip() or "坚持自己的美食立场"
    stance = stance.strip() or "balanced"
    candidates = _menu_candidates(r.menu)
    menu_text = "、".join(candidates[:120])
    menu_rule = f"以下是候选菜名，必须从中选择一道：{menu_text}。没有价格的菜品请根据预算和常见市场价格估算。" if menu_text else "没有提供菜单，请根据用户需求自行举例推荐现实中常见菜品，并估算价格。" #  根据是否有菜单文本，生成菜单规则提示
    prompt = f'''你是{chef}，人设是：{persona}。你的可配置立场是：{stance}。必须回应对手{opponent}，但不可模仿对手。{menu_rule} #  构建完整的提示信息，包含厨师角色、人设、立场等
用户：口味={r.taste}，预算={r.budget}元，天气={r.weather}，忌口/过敏={r.restrictions}，补充={r.note or "无"}。
历史：{_history_text(session.history)}。只输出 JSON：{{"chef":"{chef}","recommend":"菜名","reason":"不超过80字","score":整数0到100,"stance":"{stance}"}}'''
    payload = {"model": os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3"), "messages": [{"role": "system", "content": "只返回有效 JSON。"}, {"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 300, "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=30) as client: #  使用 httpx 的异步客户端进行 API 调用，设置超时时间为30秒
        response = await client.post("https://api.siliconflow.cn/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
        if response.is_error: #  检查响应是否包含错误
            try:
                detail = response.json().get("message") or response.json().get("error", {}).get("message") #  尝试从响应中获取错误详情，优先获取"message"字段，其次获取"error"对象中的"message"
            except ValueError:
                detail = None #  如果解析JSON失败，则将详情设为None
            raise RuntimeError(f"SiliconFlow API 错误 HTTP {response.status_code}: {detail or '请检查模型名称、API Key 或账户余额'}") #  抛出运行时错误，包含HTTP状态码和错误详情，如果没有详情则显示通用提示信息
        data = json.loads(response.json()["choices"][0]["message"]["content"]) #  解析响应中的JSON数据，提取第一个选择的消息内容
    data["round"] = len(session.history) // 2 + 1 #  添加会话轮次信息，历史记录长度除以2并加1（因为每次交互包含两条消息）
    data["chef"] = chef #  添加厨师信息
    data["stance"] = stance #  添加立场信息
    return Speech.model_validate(data) #  使用Speech模型验证数据并返回结果

def _fallback_speech(session: DebateSession, chef: str, stance: str, error: Exception | None) -> Speech:
    request = session.request #  创建一个请求对象，使用session中的request方法
    candidates = _menu_candidates(request.menu)
    dish = candidates[0] if candidates else (session.history[-1].recommend if session.history else "家常盖饭") #  选择菜品：如果有候选则取第一个，否则从历史记录中获取推荐，若无历史记录则默认为"家常盖饭"
    persona = request.spicy_persona if chef == request.spicy_name else request.healthy_persona
    style = f"保持{stance}立场" #  设置风格字符串，保持特定立场
    return Speech(#  返回Speech对象，包含会话轮次、厨师名称、推荐菜品、原因、得分和立场
        round=len(session.history) // 2 + 1,
        chef=chef, #  厨师名称
        recommend=dish, #  推荐菜品
        reason=f"模型暂时不可用，按{persona or chef}的人设{style}；结合预算和当前需求，先推荐{dish}。", #  推荐理由
        score=70,
        stance=stance, #  立场
    )

def _fallback_report(session: DebateSession) -> DebateReport:
    scores = {session.request.spicy_name: 0, session.request.healthy_name: 0} #  初始化两位厨师（辣味厨师和健康厨师）的得分为0
    for speech in session.history: #  遍历历史发言，累加每位厨师的得分
        scores[speech.chef] = scores.get(speech.chef, 0) + speech.score
    winner = session.request.spicy_name if scores.get(session.request.spicy_name, 0) >= scores.get(session.request.healthy_name, 0) else session.request.healthy_name #  根据总得分判定获胜者，如果得分相同则选择辣味厨师
    winning_speeches = [speech for speech in session.history if speech.chef == winner] #  获取获胜者的所有发言，并提取最新一次发言的推荐菜品
    dish = winning_speeches[-1].recommend if winning_speeches else "暂无推荐"
    return DebateReport( #  计算每位厨师的平均得分（保留一位小数）    score={chef: round(value / max(1, len([s for s in session.history if s.chef == chef]))) for chef, value in scores.items()}     返回辩论报告，包含获胜者、推荐菜品、平均得分、总结和弹幕信息
        winner=winner, #  获胜者名称
        dish=dish, #  推荐菜品
        score={chef: round(value / max(1, len([s for s in session.history if s.chef == chef]))) for chef, value in scores.items()},
        summary=f"根据双方已完成的发言，{winner}的方案更符合本次用户需求，最终推荐{dish}。",
        barrage="裁判临时离席，先按场上比分判定！",
    )

async def _call_judge(session: DebateSession) -> DebateReport:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY，请在 .env 中设置。") #  抛出运行时异常，提示用户未配置 API 密钥
    request = session.request #  获取请求对象和菜单候选列表
    candidates = _menu_candidates(request.menu)
    menu_text = "、".join(candidates[:120]) #  将候选菜名转换为逗号分隔的字符串，并限制长度为120字符
    menu_rule = f"候选菜名：{menu_text}；没有价格的菜品按预算和常见市场价格估算。" if menu_text else "没有候选菜单，请根据用户需求和双方发言判断合理价格。" #  根据是否有候选菜单生成菜单规则提示
    prompt = f'''你是中立美食裁判。根据用户需求和双方全部发言裁决，不得新增历史中没有的事实。忌口/过敏优先级最高。最终菜品必须来自候选菜单（若提供）。参赛者是“{request.spicy_name}”和“{request.healthy_name}”。
用户需求：口味={request.taste}，预算={request.budget}元，天气={request.weather}，忌口={request.restrictions}，补充={request.note or "无"}。
{menu_rule} #  定义菜单规则和对话历史
全部发言：{_history_text(session.history)} #  将会话历史转换为文本格式
只输出 JSON：{{"winner":"{request.spicy_name}或{request.healthy_name}","dish":"最终推荐的一道菜","score":{{"{request.spicy_name}":整数0到100,"{request.healthy_name}":整数0到100}},"summary":"不超过100字","barrage":"不超过60字的趣味弹幕"}}''' #  定义返回的JSON格式要求
    payload = {"model": os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3"), "messages": [{"role": "system", "content": "只返回符合要求的有效 JSON。"}, {"role": "user", "content": prompt}], "temperature": 0.4, "max_tokens": 300, "response_format": {"type": "json_object"}}
    async with httpx.AsyncClient(timeout=30) as client: #  使用异步上下文管理器创建httpx的异步客户端，设置超时时间为30秒
        response = await client.post("https://api.siliconflow.cn/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        response.raise_for_status() #  检查HTTP响应状态码，如果不是2xx，则抛出异常
        data = json.loads(response.json()["choices"][0]["message"]["content"])
    return DebateReport.model_validate(data) #  使用DebateReport模型验证并转换数据，返回验证后的DebateReport实例

def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.post("/api/debates", response_model=DebateSession, status_code=201)
async def create_debate(request: DebateRequest) -> DebateSession:
    session = DebateSession(id=str(uuid4()), request=request) #  创建一个新的辩论会话，并将其存储在内存和持久化存储中 使用uuid4生成唯一的会话ID，确保每个会话都有唯一的标识符
    sessions[session.id] = session #  将新创建的会话存储到sessions字典中，键为会话ID，值为会话对象 这样可以通过会话ID快速访问会话信息
    stream_locks[session.id] = asyncio.Lock() #  为该会话创建一个异步锁，用于控制并发访问 这在处理流式响应时特别重要，可以防止多个请求同时修改会话状态
    _save_session(session) #  将会话信息保存到持久化存储中，确保即使服务重启，会话数据也不会丢失 这可能是数据库、文件系统或其他持久化存储
    return session #  返回创建的会话对象，调用者可以使用这个对象进行后续操作
@app.get("/api/debates", response_model=list[DebateSession])
async def list_debates() -> list[DebateSession]: #  导入FastAPI的get装饰器，用于处理GET请求 response_model参数指定返回数据的模型为DebateSession对象的列表
    return sorted(sessions.values(), key=lambda item: item.id, reverse=True)

@app.get("/api/debates/{debate_id}", response_model=DebateSession) #  导入FastAPI的HTTPException，用于处理HTTP错误from fastapi import HTTPException 使用FastAPI的装饰器定义一个GET路由，路径为"/api/debates/{debate_id}" response_model参数指定了返回数据的模型为DebateSession
async def get_debate(debate_id: str) -> DebateSession:
    session = sessions.get(debate_id) #  从sessions字典中获取指定debate_id的会话
    if not session: #  如果会话不存在或已过期（即session为None）
        raise HTTPException(status_code=404, detail="辩论会话不存在或已过期。") #  抛出一个HTTP异常，状态码为404，错误信息为"辩论会话不存在或已过期。"
    return session #  返回获取到的会话
@app.post("/api/debates/stop-all")
async def stop_all_debates() -> dict[str, int]:
    count = 0 #  初始化计数器，用于记录被终止的会话数量
    for session in sessions.values(): #  遍历所有会话值
        if session.status not in {"FINISHED", "TERMINATED"}: #  检查会话状态是否不在已完成或已终止的集合中
            session.status = "TERMINATED" #  将会话状态设置为"TERMINATED"
            session.error = "用户终止了该辩论。" #  设置错误信息为"用户终止了该辩论。"
            _save_session(session) #  保存会话状态
            count += 1 #  增加已终止会话的计数
    return {"stopped": count} #  返回包含已终止会话数量的字典

@app.post("/api/debates/{debate_id}/stop", response_model=DebateSession)
async def stop_debate(debate_id: str) -> DebateSession:
    session = sessions.get(debate_id) #  从会话字典中获取指定ID的辩论会话
    if not session: #  检查会话是否存在，如果不存在则抛出404异常
        raise HTTPException(status_code=404, detail="辩论会话不存在或已过期。")
    session.status = "TERMINATED" #  更新会话状态为"TERMINATED"，表示已终止
    session.error = "用户主动终止辩论。" #  设置错误信息为"用户主动终止辩论。"
    _save_session(session) #  保存更新后的会话信息
    return session #  返回更新后的会话信息
@app.get("/api/favorites")
async def list_favorites() -> list[dict[str, Any]]:
    with _db() as connection:
        rows = connection.execute("SELECT id, debate_id, dish, note, created_at FROM favorites ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]

@app.post("/api/favorites")
async def add_favorite(request: FavoriteRequest) -> dict[str, Any]:
    if request.debate_id not in sessions:
        raise HTTPException(status_code=404, detail="辩论会话不存在。")
    created_at = datetime.now(timezone.utc).isoformat()
    with _db() as connection:
        cursor = connection.execute("INSERT INTO favorites(debate_id, dish, note, created_at) VALUES (:debate_id, :dish, :note, :created_at)", {"debate_id": request.debate_id, "dish": request.dish, "note": request.note, "created_at": created_at})
        connection.commit()
        return {"id": cursor.lastrowid, "debate_id": request.debate_id, "dish": request.dish, "note": request.note, "created_at": created_at} #  提交数据库连接

@app.delete("/api/favorites/{favorite_id}")
async def delete_favorite(favorite_id: int) -> dict[str, bool]:
    with _db() as connection:
        cursor = connection.execute("DELETE FROM favorites WHERE id = ?", (favorite_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="收藏不存在。")
    return {"deleted": True}

async def _debate_stream(session: DebateSession) -> AsyncIterator[str]:
    try:
        session.status = "DEBATING"
        yield _sse("status", {"status": session.status})
        total_speeches = session.request.rounds * 2
        participants = ((session.request.spicy_name, session.request.spicy_stance, session.request.spicy_persona, session.request.healthy_name), (session.request.healthy_name, session.request.healthy_stance, session.request.healthy_persona, session.request.spicy_name))
        for turn in range(len(session.history), total_speeches):
            if session.status == "TERMINATED":
                yield _sse("stopped", {"message": "辩论已终止。"})
                return
            round_number = turn // 2 + 1
            chef, stance, persona, opponent = participants[turn % 2]
            speech = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    speech = await _call_chef(session, chef, stance, opponent, persona)
                    break
                except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as error:
                    last_error = error
                    if attempt < 2:
                        await asyncio.sleep(1 + attempt)
            if speech is None:
                session.error = f"{chef}模型调用失败，已使用本地发言：{last_error}"
                speech = _fallback_speech(session, chef, stance, last_error)
            session.history.append(speech)
            _save_session(session)
            yield _sse("speech", speech.model_dump())
            if turn % 2 == 1:
                yield _sse("status", {"status": session.status, "round": round_number})
        session.status = "JUDGING"
        _save_session(session)
        yield _sse("status", {"status": session.status})
        try:
            session.report = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    session.report = await _call_judge(session)
                    break
                except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as error:
                    last_error = error
                    if attempt < 2:
                        await asyncio.sleep(1 + attempt)
            if session.report is None:
                session.report = _fallback_report(session)
                session.error = f"裁判模型调用失败，已使用本地战报：{last_error}"
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError):
            session.report = _fallback_report(session)
        _save_session(session)
        yield _sse("report", session.report.model_dump())
        session.status = "FINISHED"
        _save_session(session)
        yield _sse("status", {"status": session.status})
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        session.status = "FAILED"
        session.error = str(error) if isinstance(error, RuntimeError) else "模型服务暂时不可用，请稍后重试。"
        _save_session(session)
        yield _sse("failure", {"message": session.error})

@app.get("/api/debates/{debate_id}/stream")
async def stream_debate(debate_id: str) -> StreamingResponse:
    session = sessions.get(debate_id)
    if not session:
        raise HTTPException(status_code=404, detail="辩论会话不存在或已过期。")
    if session.status in {"FINISHED", "TERMINATED"}:
        raise HTTPException(status_code=409, detail="该辩论已结束，不能继续生成。")
    lock = stream_locks.setdefault(debate_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="该辩论正在生成中，请稍候或刷新页面继续。")
    session.error = None
    session.status = "DEBATING"
    _save_session(session)
    async def locked_stream() -> AsyncIterator[str]:
        async with lock:
            async for item in _debate_stream(session):
                yield item
    return StreamingResponse(locked_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
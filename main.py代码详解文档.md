# backend/main.py 代码深度详解文档

> 本文档针对 `backend/main.py` 的每一个数据模型类（Class）、内部辅助函数（Helper Function）、API 路由处理函数（Endpoint）以及全局状态管理进行全面、逐行的功能与逻辑解析。
> **注意：遵循项目规范，本解析文档仅作说明，不修改 `backend/main.py` 的任何既有代码。**

---

## 目录
1. [模块总体架构与全局配置](#1-模块总体架构与全局配置)
2. [Pydantic 数据模型类详解 (Class)](#2-pydantic-数据模型类详解-class)
   - [2.1 RecommendRequest](#21-recommendrequest)
   - [2.2 RecommendResponse](#22-recommendresponse)
   - [2.3 DebateRequest 与 apply_defaults](#23-debaterequest-与-apply_defaults)
   - [2.4 Speech](#24-speech)
   - [2.5 DebateReport](#25-debatereport)
   - [2.6 DebateSession](#26-debatesession)
   - [2.7 FavoriteRequest](#27-favoriterequest)
3. [数据库与本地持久化机制](#3-数据库与本地持久化机制)
   - [3.1 _db()](#31-_db)
   - [3.2 _init_db()](#32-_init_db)
   - [3.3 _save_session()](#33-_save_session)
   - [3.4 _load_sessions()](#34-_load_sessions)
4. [核心业务与模型交互逻辑](#4-核心业务与模型交互逻辑)
   - [4.1 _history_text()](#41-_history_text)
   - [4.2 _menu_candidates()](#42-_menu_candidates)
   - [4.3 _call_chef()](#43-_call_chef)
   - [4.4 _fallback_speech()](#44-_fallback_speech)
   - [4.5 _call_judge()](#45-_call_judge)
   - [4.6 _fallback_report()](#46-_fallback_report)
   - [4.7 _sse()](#47-_sse)
   - [4.8 _debate_stream()](#48-_debate_stream)
5. [API 路由处理函数详解 (Endpoints)](#5-api-路由处理函数详解-endpoints)
6. [并发安全与容错降级体系总结](#6-并发安全与容错降级体系总结)

---

## 1. 模块总体架构与全局配置

`backend/main.py` 是整个“干饭辩论赛”系统的核心后端驱动模块，基于 **FastAPI + Pydantic + SQLite + Server-Sent Events (SSE)** 构建，兼备以下关键职责：
- **Web 服务与单页静态路由**：加载并下发前端页面；
- **请求验证与数据清洗**：通过 Pydantic 强校验用户输入，并在缺失时填充缺省值；
- **异步模型通信**：通过 `httpx.AsyncClient` 高并发调用 SiliconFlow 兼容的 Chat Completions 大模型接口；
- **状态机与流式推送**：基于 Python 异步生成器（AsyncIterator）和 SSE 标准，将辩论每一步实时输出给客户端；
- **高可用容错机制**：内置重试计数器、候选菜单智能提取、本地规则兜底发言与均分判决战报；
- **轻量持久化与断点续传**：基于 SQLite 数据库实现历史存储、会话现场恢复与菜品收藏。

### 全局变量与配置项说明
- `BASE_DIR = Path(__file__).resolve().parent.parent`：获取当前代码文件上两级绝对路径，以此精确定位项目根目录、前端静态文件与数据库位置，消除不同操作系统的工作目录相对路径漂移风险。
- `load_dotenv(BASE_DIR / ".env")`：优先从根目录 `.env` 加载环境变量（如 `SILICONFLOW_API_KEY`、`SILICONFLOW_MODEL` 等），实现环境隔离与凭据不入库。
- `app = FastAPI(title="干饭辩论赛 - Sprint 4")`：初始化 FastAPI 顶层单例，开启自动 Swagger `/docs` 文档与路由挂载。
- `sessions: dict[str, DebateSession] = {}`：会话内存快速索引缓存，键为 `session_id`，值为反序列化的会话对象，便于在流式生命周期内高频读写。
- `DB_FILE = BASE_DIR / "ganfan.sqlite3"`：定义本地 SQLite 数据库文件的存储绝对路径。
- `stream_locks: dict[str, asyncio.Lock] = {}`：为每一个活跃会话维护一个异步并发锁（`asyncio.Lock`），杜绝同一会话被前端或重连机制并发打开多个 SSE 线程造成模型重复计费与状态错乱。

---

## 2. Pydantic 数据模型类详解 (Class)

本系统全面采用 Pydantic 2.x 定义业务领域数据契约，不仅承担序列化/反序列化职责，还承担运行时的严格类型校验与边界防御。

### 2.1 `RecommendRequest`
- **代码位置**：第 26-36 行
- **继承体系**：`pydantic.BaseModel`
- **业务定位**：基础用餐偏好输入模型，兼用于 Sprint 1 单 Agent 推荐。
- **字段定义与约束**：
  - `taste: str = Field(min_length=1, max_length=100)`：用户口味偏好（如“想吃重辣”、“清淡温润”），限制 1-100 字，禁止空输入。
  - `budget: int = Field(ge=1, le=500)`：预算约束，数值范围必须在 [1, 500] 元区间。
  - `weather: str = Field(min_length=1, max_length=50)`：就餐天气（如“暴雨湿冷”、“晴天微风”），长度 1-50 字。
  - `restrictions: str = Field(default="无", max_length=200)`：食物忌口/过敏原（如“不吃香菜”、“花生严重过敏”），最高优先级安全约束。
  - `note: str = Field(default="", max_length=300)`：补充场景说明（如“一个人吃”、“附近只有食堂”）。

### 2.2 `RecommendResponse`
- **代码位置**：第 39-48 行
- **继承体系**：`pydantic.BaseModel`
- **业务定位**：单 Agent 结构化推荐结果返回模型。
- **字段定义**：
  - `dish: str`：推荐菜品名称。
  - `reason: str`：基于用户偏好与天气的推导理由（控制在 60 字以内）。
  - `tip: str`：针对该菜品的点餐或搭配小建议。

### 2.3 `DebateRequest` 与 `@model_validator apply_defaults`
- **代码位置**：第 49-82 行
- **继承体系**：`RecommendRequest`（继承其全部基础偏好字段）
- **业务定位**：双 Agent 辩论会话创建请求模型，承载多轮交互和自定义人设/菜单需求。
- **扩展字段**：
  - `rounds: int = Field(default=3, ge=1, le=5)`：辩论交锋轮数，限制为 1 到 5 轮，默认 3 轮（即共 6 次厨师发言）。
  - `spicy_name: str = Field(default="辣子哥", max_length=30)`：正方大厨名称。
  - `healthy_name: str = Field(default="清补凉", max_length=30)`：反方大厨名称。
  - `spicy_stance: str = Field(default="spicy", max_length=100)`：正方立场（如“香辣开胃”、“肉食优先”）。
  - `healthy_stance: str = Field(default="healthy", max_length=100)`：反方立场（如“清淡均衡”、“低脂低油”）。
  - `spicy_persona: str = Field(default="火爆川菜大厨，无辣不欢", max_length=200)`：正方性格与人设 Prompt。
  - `healthy_persona: str = Field(default="温和粤菜师傅，讲究本味和均衡", max_length=200)`：反方性格与人设 Prompt。
  - `menu: str = Field(default="", max_length=50000)`：候选菜单文本（支持多行/CSV转义字符，上限扩展至 50000 字符以包容上百条菜单）。
- **`apply_defaults(self)` 逻辑剖析**：
  - 采用 `@model_validator(mode="after")` 后置装饰器。
  - **核心价值**：用户在前端即使清空文本框或提交纯空格，后端的清洗逻辑会自动将其无缝替换为默认值，确保后续 Prompt 不会出现空立场或人设空白导致的模型人格崩溃。

### 2.4 `Speech`
- **代码位置**：第 83-91 行
- **业务定位**：单次大厨辩论发言的数据载体。
- **字段定义**：
  - `round: int`：所属轮次（1, 2, 3...）。
  - `chef: str`：发言者身份名称。
  - `recommend: str`：本轮主推的具体菜品。
  - `reason: str`：发言与辩驳理由（包含对对方前序观点的反驳）。
  - `score: int = Field(ge=0, le=100)`：模型对自己方案契合度的自我打分（0-100分）。
  - `stance: str`：本轮所持的核心立场标签。

### 2.5 `DebateReport`
- **代码位置**：第 92-102 行
- **业务定位**：裁判 Agent 输出的最终辩论战报裁决模型。
- **字段定义**：
  - `winner: str`：本场辩论胜出者姓名。
  - `dish: str`：全场最终建议用户品尝的这道菜品。
  - `score: dict[str, int]`：裁判对双方全场表现给出的最终得分映射字典。
  - `summary: str`：中立权威的裁决总结（解释为何该菜品最契合用户约束）。
  - `barrage: str`：趣味吐槽弹幕文本，增加产品娱乐互动性。

### 2.6 `DebateSession`
- **代码位置**：第 103-111 行
- **业务定位**：单次辩论全生命周期的聚合根实体（Aggregate Root）。
- **字段定义**：
  - `id: str`：UUID 唯一标识码。
  - `status: str = "PENDING"`：状态机标识，状态集包括 `PENDING`（刚创建）、`DEBATING`（双厨交锋中）、`JUDGING`（裁判裁决中）、`FINISHED`（正常结束）、`FAILED`（异常中断）、`TERMINATED`（人工终止）。
  - `request: DebateRequest`：用户原始请求与配置快照。
  - `history: list[Speech]`：该会话按时间先后记录的完整发言序列。
  - `report: DebateReport | None`：最终战报（未完赛前为 None）。
  - `error: str | None`：异常追踪提示，用于排错与前端友好展示。

### 2.7 `FavoriteRequest`
- **代码位置**：第 112-120 行
- **业务定位**：用户将战报中的满意菜品收藏进数据库时的提交载荷。
- **字段定义**：`debate_id`（关联的辩论ID）、`dish`（菜品名称，1-100字）、`note`（用户个人备忘，最多300字）。

---

## 3. 数据库与本地持久化机制

为了摆脱第三方复杂数据库安装门槛，同时保障断网重连、浏览器刷新与历史回顾能力，系统内置了轻量安全的 SQLite 原生持久化引擎。

### 3.1 `_db() -> sqlite3.Connection`
- **代码位置**：第 134-144 行
- **功能逻辑**：
  - 连接项目根目录下的 `ganfan.sqlite3` 文件。
  - 将数据库连接的 `row_factory` 明确设置为 `sqlite3.Row`。
  - **核心价值**：支持以字典列名形式（如 `row["data"]`、`row["status"]`）读取查询结果，使 SQL 处理更加健壮可读。

### 3.2 `_init_db() -> None`
- **代码位置**：第 146-160 行
- **功能逻辑**：
  - 执行幂等建表语句（`CREATE TABLE IF NOT EXISTS`）。
  - **`debates` 表**：存储完整的会话实体。包含 `id`（主键文本）、`data`（JSON 序列化的会话全貌）、`status`（状态文本索引）以及 `updated_at`（更新时间戳）。
  - **`favorites` 表**：存储收藏菜品记录。包含 `id`（自增主键）、`debate_id`（关联会话ID）、`dish`（菜名）、`note`（备注）和 `created_at`（创建时间戳）。

### 3.3 `_save_session(session: DebateSession) -> None`
- **代码位置**：第 162-168 行
- **功能逻辑**：
  - 获取当前标准的 ISO-8601 UTC 时间字符串。
  - 将传入的 `session` 实例全量序列化为 JSON 字符串。
  - 使用 SQLite 的 `UPSERT` 语法（`INSERT INTO ... ON CONFLICT(id) DO UPDATE SET ...`），保证新建时插入、已有会话更新时原子覆盖。
  - **参数安全**：使用命名参数字典绑定（`:id`, `:data`, `:status`, `:updated_at`），从底层杜绝参数个数错配与 SQL 注入风险。

### 3.4 `_load_sessions() -> None`
- **代码位置**：第 170-197 行
- **功能逻辑**：
  - 系统启动时自执行该函数，首先调用 `_init_db()` 完成建表；
  - 倒序读取 `debates` 表中的历史数据，通过 `DebateSession.model_validate` 重新载入全局 `sessions` 字典，并为每一个活跃会话重建 `asyncio.Lock()`；
  - **向前兼容旧版本**：若本地检测到旧版本的 `debates.json` 且数据库尚为空，会自动遍历旧 JSON 数据并一次性迁移写入 SQLite，保障早期用户数据平滑无损。

---

## 4. 核心业务与模型交互逻辑

### 4.1 `_history_text(history: list[Speech]) -> str`
- **代码位置**：第 298-299 行
- **功能逻辑**：
  - 将结构化发言列表转换成自然语言上下文字符串。
  - 格式如：`第1轮 辣子哥：推荐麻辣香锅；理由：晴天吃辣开胃...\n第1轮 清补凉：推荐清蒸鲈鱼...`。
  - 若发言列表为空，输出安全占位符“暂无发言。”，防止向大模型 Prompt 传入空历史造成歧义。

### 4.2 `_menu_candidates(menu: str) -> list[str]`
- **代码位置**：第 301-315 行
- **设计背景与核心算法**：
  - 针对上传 CSV、XLSX 或手工在输入框粘贴的各种杂乱菜单格式，设计了高容错的多策略提取算法：
  - **策略一**：利用正则 `re.search(r"菜品：([^；,，]+)", line)` 智能抓取结构化标签中的纯菜名，剔除价格、分类、主要食材等多余字符；
  - **策略二**：若无结构化前缀，则按中英文逗号、分号（`[,，;；]`）二次切分并过滤掉属性前缀；
  - **去重与保序**：通过 `list(dict.fromkeys(candidates))` 消除重复菜名，并保留首次出现次序；
  - **关键防御**：彻底解决早前版本因格式切分不当导致大模型或兜底逻辑将整段 CSV 长文本误判为单一菜名的重大缺陷。

### 4.3 `_call_chef(session, chef, stance, opponent, persona) -> Speech`
- **代码位置**：第 317-343 行
- **功能逻辑**：
  - 动态抽取前 120 个候选菜名并拼装菜单规则；
  - 组装具有强约束力的 Chef Prompt，限定其必须紧扣自身立场（`stance`）与性格（`persona`），正面反驳对手（`opponent`）前序观点，同时优先遵循忌口与预算；
  - 注入 `response_format: {"type": "json_object"}` 强制大模型以纯 JSON 响应；
  - 采用异步 HTTP POST（超时设为 30s）请求 SiliconFlow 平台；
  - 若 HTTP 返回 4xx/5xx，精准提取 API 返回的错误消息并抛出详细的 `RuntimeError`，便于前端展示具体原因。

### 4.4 `_fallback_speech(session, chef, stance, error) -> Speech`
- **代码位置**：第 345-358 行
- **容错保底逻辑**：
  - 当大模型服务遭遇断网、网关 504 超时或配额耗尽连续重试 3 次仍失败时被触发；
  - 从 `_menu_candidates` 解析出的真实菜名列表中提取第 1 个菜名（若无菜单则沿用上一条推荐或默认“家常盖饭”）；
  - 自动生成一条符合当前厨师人设与立场的标准 `Speech` 对象，评分保底设为 70 分；
  - **业务价值**：防止辩论在中途突发卡死，让用户能够继续走完整场辩论流程。

### 4.5 `_call_judge(session: DebateSession) -> DebateReport`
- **代码位置**：第 374-393 行
- **功能逻辑**：
  - 作为第三位独立 Agent（美食评审裁判），接收完整的辩论历史上下文；
  - 强制温度参数 `temperature=0.4`（较低温度以保证评分和裁决的严肃与客观）；
  - 裁判依据“用户偏好吻合度”、“忌口严格遵循度”、“双方论据合理性”对双方厨师打分，评选出最终胜出者、最佳菜品、终局总结以及一行趣味弹幕。

### 4.6 `_fallback_report(session: DebateSession) -> DebateReport`
- **代码位置**：第 360-373 行
- **裁决兜底与算法解析**：
  - 若调用裁判模型连续失败或遭遇上游异常，调用该函数进行无模型保底决胜；
  - **计分法则**：遍历会话历史中每位大厨的历史发言自评分，累加后求其算术平均值（`round(value / count)`）；
  - **胜者判定**：总均分高者胜出（若相等则正方优先）；
  - **推荐菜品**：取胜方大厨在最后一轮辩论中所提出的主推菜品；
  - **弹幕提示**：“裁判临时离席，先按场上比分判定！”，兼顾趣味性与系统韧性。

### 4.7 `_sse(event: str, data: Any) -> str`
- **代码位置**：第 395-396 行
- **功能逻辑**：
  - 依据 W3C Server-Sent Events (SSE) 协议标准格式封装数据包；
  - 格式输出为：`event: {event}\ndata: {json_str}\n\n`；
  - 设置 `ensure_ascii=False`，保证中文字符直接以 UTF-8 文本无损推送，避免十六进制 Unicode 乱码。

### 4.8 `_debate_stream(session: DebateSession) -> AsyncIterator[str]`
- **代码位置**：第 460-519 行
- **状态流转与生成器引擎**：
  - 本函数是整个辩论流程的心脏，通过 `async for` 异步产出 SSE 数据流；
  - **初始化**：置 `status="DEBATING"`，向客户端下发首个 `status` 事件；
  - **双厨轮流交锋循环**：
    - 根据目标总发言条数（`rounds * 2`），由 `len(session.history)` 决定起始点，实现**断点续传**；
    - 在每一次调用前检查 `session.status == "TERMINATED"`，若用户主动终止，立即下发 `stopped` 事件并退出；
    - 厨师调用采用**3 次带退避间隔（1s, 2s）的指数重试机制**；若 3 次均失败，则优雅降级为 `_fallback_speech`；
    - 成功或兜底后立即追加历史并调用 `_save_session` 存入 SQLite，随后 yield 发射 `speech` 事件；
  - **裁判裁决阶段**：
    - 轮次结束后置 `status="JUDGING"` 并推送状态；
    - 同样进行 3 次重试调用 `_call_judge`，最终若未产出则以 `_fallback_report` 兜底；
    - yield 发送最终 `report` 事件；
  - **终局收尾**：置 `status="FINISHED"`，持久化后下发最终 `status` 事件，平稳关闭当前 SSE 连接；
  - **异常捕获**：若发生致命非预期异常，标记 `status="FAILED"`，保存数据库并向前端推送自定义 `failure` 事件。

---

## 5. API 路由处理函数详解 (Endpoints)

| 方法 | 路由路径 | 对应函数名 | 功能说明与实现细节 |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | `index()` | 返回 `FileResponse(BASE_DIR / "frontend/index.html")`，下发前端单页 UI。 |
| `POST` | `/api/menu/upload` | `upload_menu(...)` | 接收 `UploadFile`，支持 `.csv`（UTF-8/BOM）与 `.xlsx`（openpyxl 只读模式），校验文件小于 5MB，清洗首行列名并输出规范化菜单文本。 |
| `GET` | `/api/tts` | `text_to_speech(...)` | 接收 `text` 与 `voice` 参数（支持 YunxiNeural、XiaoxiaoNeural），500 字上限校验，调用 `edge_tts.Communicate` 异步生成并流式返回 MPEG 音频。 |
| `POST` | `/api/recommend` | `recommend(...)` | Sprint 1 单 Agent 推荐入口，校验 `RecommendRequest`，请求 SiliconFlow 并经 `RecommendResponse` 强校验后返回，保留向下兼容。 |
| `POST` | `/api/debates` | `create_debate(...)` | 接收 `DebateRequest` 并执行默认值补全，生成唯一 UUID，创建会话实体，注册异步互斥锁，存入 SQLite，返回状态码 201 与会话实体。 |
| `GET` | `/api/debates` | `list_debates()` | 获取所有历史辩论记录列表，按会话倒序排列，供前端“历史战报”面板查询。 |
| `GET` | `/api/debates/{debate_id}` | `get_debate(...)` | 精确查询指定会话状态与全部历史发言、战报，前端刷新页面时据此完成断点数据回显。 |
| `POST` | `/api/debates/stop-all` | `stop_all_debates()` | 遍历所有内存中处于非完成/非终止态的会话，将其批量更新为 `TERMINATED` 并持久化。 |
| `POST` | `/api/debates/{debate_id}/stop`| `stop_debate(...)` | 精确将某一个正在进行的会话状态置为 `TERMINATED`，触发异步生成器在下一跳安全退出。 |
| `GET` | `/api/favorites` | `list_favorites()` | 查询 SQLite 的 `favorites` 表，倒序返回用户收藏的所有菜品记录。 |
| `POST` | `/api/favorites` | `add_favorite(...)` | 校验会话合法性，以命名参数执行 SQL 插入，将战报菜品存入 `favorites` 表。 |
| `DELETE`| `/api/favorites/{favorite_id}`| `delete_favorite(...)` | 依据自增 ID 物理删除收藏记录，若受影响行数为 0 则抛出 404 错误。 |
| `GET` | `/api/debates/{debate_id}/stream`| `stream_debate(...)`| 开启 SSE 长连接，检查完成态/终止态，申请该会话独占的 `asyncio.Lock` 包装 `_debate_stream`，防止并发竞争。 |

---

## 6. 并发安全与容错降级体系总结

通过对 `backend/main.py` 的代码解析，可以看到系统在架构层面落实了多重高可用与健壮性防护设计：

1. **会话级并发互斥控制（`asyncio.Lock`）**：
   - 现代浏览器在网络不稳定或 SSE 断开时，常会触发重试或被用户连续点击；
   - 系统为每个会话绑定独占的 `asyncio.Lock`。若已有连接正在流式产出，后来的连接将直接收到 HTTP 409 拦截，彻底规避了多线程并发调用导致的重复扣费与状态冲突。

2. **多层次容错降级矩阵**：
   - **重试层**：单次模型调用失败后引入指数退避（1s、2s）重试 3 次，过滤临时性网络抖动；
   - **发言兜底层**：厨师模型连续 3 次失败时，调用 `_fallback_speech` 依据候选菜单或上轮菜品产出符合当前人设的保底发言，辩论不掉线；
   - **战报兜底层**：裁判模型连续失败时，调用 `_fallback_report` 根据历史自评分数通过均分算法裁决胜负与推荐菜，保障最终结论必定交付；
   - **输入清洗层**：通过 Pydantic 校验和 `_menu_candidates` 正则提取，把 354 条 CSV 菜单长文本转化为干净精简的菜名数组，既防御了大模型 Prompt Token 溢出，又杜绝了切词错乱。

3. **数据一致性与零外部依赖**：
   - 采用标准 SQLite 存储，利用 UPSERT 与参数化查询避免 SQL 错误；
   - 系统启动阶段自动迁移旧版本 JSON 数据，并提供“终止全部未完成辩论”功能，彻底清理历史悬挂脏数据。

---

> **代码完整性说明**：本模块（`backend/main.py`）所有既有代码保持原样，未做任何修改与重构。

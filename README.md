# 干饭辩论赛
> 让两位立场鲜明的 AI 大厨为「今天吃什么」展开结构化辩论，生成可解释、有趣且可执行的用餐建议。

## 项目目标
用户填写口味、预算、天气和忌口等条件后，系统依次驱动「辣子哥」与「清补凉」进行 3 轮交锋，再由裁判 Agent 输出最终战报。产品重点是可控的多 Agent 协作、清晰的实时体验和稳定的结构化结果。

## 核心流程
```text
提交需求 -> 创建辩论会话 -> 双厨轮流发言 -> 裁判总结 -> 展示战报
```

1. 用户输入偏好，例如：`想吃辣，预算 30 元，晴天，不吃香菜`。
2. 川辣派「辣子哥」先提出香辣推荐并回应当前上下文。
3. 粤式养生派「清补凉」针对对方观点反驳，给出清淡方案。
4. 重复至最大轮数（默认 3，最大 5），避免无限对话。
5. 裁判 Agent 依据全部发言生成胜者、菜品、评分和趣味弹幕。

## 功能范围
### 当前版本（Sprint 1-5）
- 偏好表单：口味、预算、天气、忌口/过敏和补充说明。
- 双 Agent 固定人设辩论：辣子哥坚持 `spicy`，清补凉坚持 `healthy`。
- 服务端严格控制 1-5 轮，默认 3 轮；每轮双方各发言一次。
- SSE 实时推送状态、发言、最终战报和失败事件。
- 裁判 Agent 根据完整历史输出胜者、最终菜品、比分、总结和弹幕。
- 模型调用失败时保留已完成进度，并提供本地比分兜底战报。
- 浏览器刷新后恢复上次会话、表单和已完成发言，继续生成缺失内容。
- 模型生成文本使用安全 DOM API 展示，不直接拼接为 HTML。
- 支持 SQLite 历史战报、收藏菜品、终止当前/全部未完成会话，并兼容旧 `debates.json` 自动迁移。

### Sprint 4 已完成
- 表单支持自定义两位 Agent 的名称、立场和人设描述，名称与立场会传入辩论和裁判 Prompt。
- 表单支持输入候选菜单；有菜单时 Agent 和裁判优先从菜单选择。
- 支持上传 UTF-8 CSV 或 XLSX 菜单；文件菜单会自动填入文本框。
- 文件菜单和手工菜单同时存在时，两者合并为候选菜单；没有菜单时 Agent 自行举例。
- 菜单行可以只有菜名，没有价格时 Agent 按预算和常见价格估算。
- 新增 `Dockerfile` 和 `docker-compose.yml`，支持容器启动及 SQLite 数据库持久化挂载。
- 新增 GitHub Actions CI：安装依赖、Python 编译检查和 Docker 镜像构建。

### 后续拓展
- 自定义 Agent 名称和更多可配置立场。
- 接入食堂真实菜单 API，对菜品库存和价格进行过滤。
- edge-tts 语音播报、音效及分享海报。
- 历史战报列表、收藏菜品和数据库部署。
- edge-tts 语音播报、轮次提示音和 Canvas 分享海报已在当前版本提供。

## 技术架构
```text
浏览器：原生 HTML + CSS + JavaScript
  表单 -> POST 创建会话
  EventSource <- SSE：status / speech / report / failure
  localStorage：保存当前会话 ID，刷新后恢复
              |
              | HTTP + Server-Sent Events
              v
FastAPI（backend/main.py）
  Pydantic 请求/响应模型
  会话状态机与轮次控制
  asyncio.Lock 并发保护
  SQLite（ganfan.sqlite3）会话、历史和收藏持久化
              |
              | HTTP JSON（OpenAI 兼容 Chat Completions）
              v
SiliconFlow
  辣子哥 Agent / 清补凉 Agent / 裁判 Agent
```

后端通过 `httpx.AsyncClient` 调用 SiliconFlow，并使用 Pydantic 校验模型 JSON。API Key 只从根目录 `.env` 的 `SILICONFLOW_API_KEY` 读取；模型通过 `SILICONFLOW_MODEL` 配置，`.env` 和 `debates.json` 均不提交到仓库。

## Agent 设计
| Agent | 人设 | 代码标识 | 目标 | 关键约束 |
| --- | --- | --- | --- | --- |
| 默认 Agent | 默认人设 | 请求字段 | 目标 | 关键约束 |
| 辣子哥 | 火爆川菜大厨，无辣不欢 | `spicy_name`, `spicy_stance`, `spicy_persona` | 按用户配置的立场推荐 | 保持自身立场，必须回应对手观点 |
| 清补凉 | 温和粤菜师傅，讲究本味 | `healthy_name`, `healthy_stance`, `healthy_persona` | 按用户配置的立场推荐 | 保持自身立场，必须回应对手观点 |
| 裁判 | 中立美食评审 | `DebateReport` | 根据用户需求和辩论内容裁决 | 不新增未出现的事实，输出固定战报 JSON；失败时使用本地兜底 |

### 模型调用次数
默认 3 轮时，一次完整会话最多调用 7 次模型：

```text
3 轮 ×（辣子哥 + 清补凉）= 6 次辩论调用
裁判 = 1 次调用
总计 = 7 次
```

单次上游请求超时或返回错误不会清空已保存历史；裁判请求失败则使用 `_fallback_report` 根据已完成发言的平均分生成战报。

每次调用都传入：用户原始需求、完整历史记录、当前轮次、对手名称、Agent 名称、可配置立场、人设和输出 Schema。Prompt 中明确「你是 X，对手是 Y；不可模仿或改变对方立场」，降低角色串台风险。

### 自定义 Agent 请求字段
`POST /api/debates` 支持以下字段：

```json
{
  "spicy_name": "辣王",
  "spicy_stance": "重口味优先",
  "spicy_persona": "街头甜辣厨师，热情直接",
  "healthy_name": "养生官",
  "healthy_stance": "低糖低油优先",
  "healthy_persona": "营养师，温和理性"
}
```

名称长度限制为 30 字，立场限制为 100 字，人设限制为 200 字。未填写时使用默认的“辣子哥/清补凉”配置；旧的 `debates.json` 会通过 Pydantic 默认值保持兼容。

### 数据结构
```json
{
  "chef": "辣子哥",
  "recommend": "麻辣香锅",
  "reason": "30 元内配菜自由，晴天吃辣更开胃。",
  "score": 86,
  "stance": "spicy"
}
```

```json
{
  "winner": "辣子哥",
  "dish": "麻辣香锅",
  "score": { "辣子哥": 86, "清补凉": 74 },
  "summary": "预算与口味优先，麻辣香锅更契合本次需求。",
  "barrage": "今日辣度拉满，清补凉申请递上一碗凉茶。"
}
```

## 状态机与接口
会话状态按以下流程运行：

```text
PENDING -> DEBATING -> JUDGING -> FINISHED
              \-> FAILED
```

`rounds` 由 Pydantic 限制为 1-5，模型不能自行决定继续轮数。每条发言成功后立即写入 `debates.json`；连接中断或模型失败后，下一次打开流会从 `history.length` 对应的下一位 Agent 继续。裁判失败时使用本地兜底战报，避免 6 条发言已经完成却没有结果。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/debates` | 创建会话，传入用户偏好和轮数 |
| `GET` | `/api/debates/{id}` | 查询状态、请求参数、历史和战报 |
| `GET` | `/api/debates/{id}/stream` | SSE 推送辩论、裁判和失败事件 |
| `POST` | `/api/debates/{id}/stop` | 终止指定会话并保留历史 |
| `POST` | `/api/debates/stop-all` | 终止所有未完成会话 |
| `GET` | `/api/favorites` | 查看收藏菜品 |
| `POST` | `/api/favorites` | 收藏推荐菜品 |
| `DELETE` | `/api/favorites/{id}` | 删除收藏 |
| `POST` | `/api/recommend` | Sprint 1 单 Agent 推荐，保留兼容 |

SSE 事件：

- `status`：`DEBATING`、`JUDGING`、`FINISHED` 等状态
- `speech`：一条经过 Pydantic 校验的厨师发言
- `report`：最终裁判战报，前端将其视为结果完成信号
- `failure`：服务端失败信息；`stopped`：用户终止会话；`error` 保留给浏览器原生 EventSource 网络错误
- `GET /api/tts?text=...&voice=...`：使用 edge-tts 生成 MPEG 音频，支持 `zh-CN-YunxiNeural` 和 `zh-CN-XiaoxiaoNeural`
启动后可通过 <http://127.0.0.1:8000/docs> 查看 FastAPI 自动生成的接口文档。

## Sprint 计划
| Sprint | 交付物 | 验收标准 |
| --- | --- | --- |
| 1 | 偏好表单、单 Agent 调用、结果展示 | Given 输入「辣、30 元、晴天」，When 提交，Then 3 秒内展示一道菜及理由 |
| 2 | 双 Agent Prompt、3 轮控制链、上下文历史 | Given 输入「爱甜、预算 50」，When 发起辩论，Then 双方各发言 3 次，不串台、不无限循环 |
| 3 | 裁判战报、Pydantic 校验、SSE 与界面优化 | Given 辩论结束，When 裁判完成总结，Then 展示推荐菜品、比分和吐槽弹幕 |
| 4 | 自定义人设、菜单对接、Docker 与 CI | Given 修改川辣派描述，When 再次辩论，Then 新风格生效且另一 Agent 不受影响 |

## 质量与边界
- 请求使用 30 秒上游超时；非 JSON、字段缺失或上游错误会被捕获并转为友好失败事件。
- 每条成功发言立即持久化；连接中断后可恢复，不重复生成已保存内容。
- 忌口和过敏信息优先级最高，Prompt 要求 Agent 和裁判避免推荐冲突食材。
- 前端展示模型生成内容时按纯文本处理，避免注入风险。
- API Key 只从环境变量读取，不写入日志、README 或 `debates.json`。
- 当前项目尚未配置自动化测试；后续应覆盖状态转移、轮次上限、JSON 校验、断点恢复和 SSE 事件顺序。

## 当前目录结构
```text
.
├── backend/
│   └── main.py       # FastAPI 路由、Pydantic 模型、Agent 调用、SSE 和持久化
├── frontend/
│   └── index.html    # 表单、SSE 时间线、战报和断点恢复逻辑
├── .env              # 本地配置，不提交（由 .env.example 复制而来）
├── debates.json      # 本地会话进度，运行时生成，不提交
├── .gitignore
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

当前版本采用单文件骨架，便于 Sprint 迭代；后续增加数据库、测试或多种 Agent 后，可再拆分为 `api/`、`agents/`、`models/` 和 `services/` 模块。

## 演示脚本
演示时输入「我不吃辣，预算 35 元，阴天，有点失恋」，观察双方是否能保留各自立场并尊重忌口。战报页突出推荐菜品、比分进度和弹幕；辩论中逐条出现发言并在轮次切换时播放短提示音。这个场景能同时展示约束遵守、实时交互和产品趣味性。

## 配置与本地启动
> 不要把真实 API Key 写入 README、聊天记录或 Git。你之前公开过的 Key 应立即撤销并重新生成。

1. 安装 Python 3.11+，在项目根目录创建虚拟环境：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. 复制配置并填入你的 API Key：
   ```powershell
   Copy-Item .env.example .env
   # 编辑 .env，设置 SILICONFLOW_API_KEY
   ```
3. 在 `.env` 中设置实际可用的模型，例如：
   ```dotenv
   SILICONFLOW_MODEL=zai-org/GLM-5.3
   ```
4. 启动后端：
   ```powershell
   uvicorn backend.main:app --reload --port 8000
   ```
5. 浏览器打开 <http://127.0.0.1:8000/>，填写偏好并点击「开始双厨辩论」。
6. 查看接口文档：<http://127.0.0.1:8000/docs>。
7. 如果中途断开，刷新页面后点击「继续上次辩论」；本地进度保存在 `debates.json`。

### Sprint 4 完成标准
- 表单可分别修改两位 Agent 的名称、立场和人设，下一次辩论使用新配置且互不影响。
- 可传入候选菜单，模型推荐受菜单约束。
- `docker build` 和 CI 编译检查通过。

### Sprint 5 完成标准
- 空白的自定义名称、立场、人设和补充说明在后端自动回退到默认值。
- 支持历史战报列表、菜品收藏、指定会话终止和全部未完成会话终止。
- SQLite 保存会话与收藏，旧 `debates.json` 首次启动时自动迁移。
- API Key 只用于后端调用 SiliconFlow，不通过前端返回或展示。

### Sprint 3 完成标准
- 新增裁判 Agent，基于双方完整历史生成结构化 `winner`、`dish`、`score`、`summary` 和 `barrage`。
- SSE 按 `speech -> status(JUDGING) -> report -> status(FINISHED)` 推送，`report` 作为最终战报事件。
- 会话进度持久化到本地 `debates.json`；浏览器刷新后根据保存的会话 ID 恢复历史，并从未完成的发言继续生成。
- 前端展示推荐菜品、获胜大厨、比分、总结和趣味弹幕；模型内容按纯文本渲染。

### Sprint 2 完成标准
- `POST /api/debates` 创建 1 至 5 轮会话，默认 3 轮。
- `GET /api/debates/{id}/stream` 严格按轮次输出双方各一次 `speech`，并传入完整历史上下文。
- 会话状态按 `PENDING -> DEBATING -> FINISHED` 流转，异常进入 `FAILED`，不会无限循环。
- 前端通过 SSE 实时展示辣子哥与清补凉的发言，模型内容按纯文本/安全 DOM 展示。

### Sprint 1 完成标准
- 表单提交前完成必填项、预算范围和长度校验。
- 后端只从环境变量读取 API Key，未配置时返回明确提示。
- 模型结果经过 JSON 解析和 Pydantic 校验后才展示。
- 加载中按钮禁用并显示状态；网络或模型失败时显示可重试错误。
- 页面结果至少包含一道菜名、推荐理由和点餐建议。

## 当前限制与排障
- 会话和收藏目前保存在本地 SQLite 文件，适合单进程开发环境，不适合多实例生产部署。
- 菜单上传限制为 5MB，CSV 使用 UTF-8/UTF-8 BOM，XLSX 默认读取第一个工作表和首行列名。
- `ganfan.sqlite3` 是数据库文件；旧 `debates.json` 只用于首次自动迁移，可在确认迁移后备份或删除。
- 菜单样例文件为根目录 `menu.csv`，当前覆盖川菜、家常菜、酸甜苦辣、盖浇饭、炒饭、面食、水饺、烧烤、奶茶、甜品和饮品，可直接修改后上传。
- 一个会话通过 `asyncio.Lock` 防止重复生成；重新打开同一会话会从已保存历史继续。
- 厨师和裁判请求使用 `httpx` 30 秒超时；网络慢时可能需要刷新后继续。
- `favicon.ico` 404 不影响应用功能。

## 启动清单
- 配置 `SILICONFLOW_API_KEY` 和控制台中实际可用的 `SILICONFLOW_MODEL`。
- 启动 FastAPI 并验证 `/docs`、会话创建和 SSE 事件顺序。
- 用“中断后刷新并继续”、终止会话、历史列表和收藏场景验证 SQLite 恢复能力。
- Docker 部署需要先准备 `.env`；不要把包含 API Key 的 `.env` 构建进镜像或提交仓库。
- 生产部署前将本地 JSON 存储替换为数据库，并补充认证、限流和结构化日志。
- 语音接口依赖 edge-tts 的网络服务；浏览器自动播放策略可能要求用户先点击页面。

### Docker 启动
```powershell
docker compose up --build
```
打开 <http://127.0.0.1:8000/>。

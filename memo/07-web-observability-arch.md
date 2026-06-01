# Web + 观测体系架构决策

> 这份 memo 在写代码前先写完。目的是把"为什么这样选"先讲清楚, 避免后续在实现细节里把架构搞糊涂。

## 总体目标

把 CLI 跑的 multi-agent pipeline 变成一个 web 系统, 满足三件事:
1. 用户填表 → 触发 run
2. **实时**看每个 Agent 的状态和整个 workflow 进度 (这是观测体系的核心)
3. run 完成后展示报告

## 关键约束

| 约束 | 影响 |
|---|---|
| 简单 web 页面 | 不要 SPA 框架, 不要构建工具, 一个 HTML + 一个 CSS + 一个 JS |
| 遵循 Design.md | cream / coral / dark navy 配色; Cormorant Garamond + Inter 字体; section 96px 节奏 |
| 实时观测 | 必须流式, 不允许"完成后才看到" |
| 工程化 | TDD, 不破坏现有 69 个测试; 新模块也要带测试 |

## 技术选型

### 1. 后端框架: **FastAPI + uvicorn**

候选:
- Flask: 不原生支持 async, SSE 写起来扭
- FastAPI: 原生 async, OpenAPI 文档自动生成, 与现有 Pydantic 一体
- Starlette: 太底层, 要自己拼

选 FastAPI 的关键理由: **现有代码全部是 Pydantic v2**, FastAPI 就是为这个生态而生的, 把已有 `CandidateProfile` / `ExtractionReport` 等 schema 直接当请求/响应模型零成本。

### 2. 实时通信: **Server-Sent Events (SSE)**

候选对比:

| 方案 | 优点 | 缺点 |
|---|---|---|
| 轮询 | 简单 | 不实时, 浪费请求 |
| WebSocket | 全双工 | 协议复杂; 需要心跳; 代理穿透烦 |
| **SSE** | 单向流 + 原生 EventSource API + HTTP/1.1 标准 | 仅单向 (但我们就是单向) |

**选 SSE。** 我们的需求是"服务器推事件给前端", 完全不需要全双工。SSE 的优势:
- 浏览器原生 `EventSource` API, 不需要任何 JS 库
- 自动重连
- 走标准 HTTP, 通过任何 nginx / 防火墙
- 协议人类可读, 调试用 `curl -N` 直接看流

加 **sse-starlette** 库: 提供心跳 + 断连检测 + 标准 SSE 格式封装。约 50 行的依赖, 值得加。

### 3. 前端: **零构建** — 原生 HTML/CSS/JS

候选:
- React/Vue/Svelte: 都需要构建步骤, 与"简单 web 页面"冲突
- HTMX: 适合传统模板渲染, 但实时观测面板用 JS 操作 DOM 更直接
- **Vanilla JS + EventSource**: 一个文件, 零依赖

选 vanilla。整个前端 < 500 行 JS, 不需要 React 的代价。直接用 `EventSource` + `fetch` + `document.querySelector`。

Google Fonts 替代品:
- Copernicus → **Cormorant Garamond** (Design.md 已建议)
- StyreneB → **Inter** (Design.md 已建议)
- JetBrains Mono → **JetBrains Mono** (本身就是开源)

### 4. 并发模型: **线程池 + asyncio.Queue 桥接**

问题: 现有 Pipeline 是同步的 (anthropic SDK 调用 `messages.create` 是同步), 但 FastAPI 是 async-first。如果 Pipeline 直接在 event loop 里跑, 整个进程就只能服务一个 run。

解决: **用 `asyncio.run_in_executor` 把 pipeline 丢到线程池**。事件流从 pipeline 线程通过 `asyncio.Queue` 传到 SSE 处理器。

```
┌─────────────────────────┐
│   FastAPI event loop    │
│   (async)               │
│                         │
│   /runs (POST) ─────────┼──► spawn thread ────► Pipeline.run()
│                         │                          │ emit
│   /events (SSE) ◄───────┼──── asyncio.Queue ◄──────┘
└─────────────────────────┘
```

EventBus 内部用 `queue.Queue` (thread-safe), SSE 用 `asyncio.to_thread(queue.get)` 把同步 get 包装成 async。这样两边都不阻塞 event loop。

### 5. 状态持久化: **In-Memory + Disk**

- **In-Memory `RunRegistry`**: 维护活跃 run 的 EventBus, 让 SSE 能查到流
- **磁盘**: 现有 ArtifactStore + run transcript 已经存了, 不重复

如果进程重启, 活跃 run 状态丢失。这对 MVP 来说**可以接受** — 报告本身在磁盘上, 只是观测流断了。

## EventBus 设计

```python
class EventType(str, Enum):
    RUN_STARTED      = "run.started"
    RUN_COMPLETED    = "run.completed"
    RUN_FAILED       = "run.failed"
    STAGE_STARTED    = "stage.started"
    STAGE_COMPLETED  = "stage.completed"
    AGENT_STARTED    = "agent.started"
    AGENT_COMPLETED  = "agent.completed"
    AGENT_FAILED     = "agent.failed"
    ARTIFACT_WRITTEN = "artifact.written"
    GATE_EVALUATED   = "gate.evaluated"
    LOG              = "log"

@dataclass
class Event:
    seq: int                  # monotonic, for client reconnect resume
    run_id: str
    timestamp: str            # ISO8601 UTC
    type: EventType
    payload: dict
```

### 接口

```python
class EventBus:
    def emit(self, type: EventType, **payload) -> Event
    def subscribe(self) -> queue.Queue            # returns a Queue to read from
    def unsubscribe(self, q: queue.Queue) -> None
    def snapshot(self) -> list[Event]              # all events so far
    def is_terminal(self) -> bool                  # run.completed | run.failed seen
```

### 接入点

| 接入位置 | 发射事件 |
|---|---|
| `Pipeline.run()` 入口 | `RUN_STARTED` |
| `Pipeline.run()` 每个 stage 入口 | `STAGE_STARTED` |
| `Pipeline.run()` 每个 stage 退出 | `STAGE_COMPLETED` |
| `Pipeline.run()` gate 评估后 | `GATE_EVALUATED` |
| `BaseAgent.run()` 入口 | `AGENT_STARTED` |
| `BaseAgent.run()` 退出 | `AGENT_COMPLETED` |
| `BaseAgent.run()` 失败 | `AGENT_FAILED` |
| `ArtifactStore.put()` | `ARTIFACT_WRITTEN` (可选) |
| `Pipeline.run()` 完成 / 失败 | `RUN_COMPLETED` / `RUN_FAILED` |

为了**最小侵入式**, EventBus 通过 `AgentContext.bus` 注入。**bus 为 None 时不发任何事件** — 这意味着所有现有 unit/integration test 不需要改动, 旧的 CLI 入口也照常工作。

## API 设计

```
POST   /api/runs
       Body: { resume_text, target_role, turns, min_incidents, candidate_id }
       Resp: { run_id, status_url, events_url }

GET    /api/runs/{run_id}/events           # SSE stream
       Optional query: last_event_id (resume)

GET    /api/runs/{run_id}/snapshot         # JSON snapshot of all events so far

GET    /api/runs/{run_id}/report           # final ExtractionReport JSON (404 if not done)

POST   /api/runs/{run_id}/cancel           # request cancel (best-effort)

GET    /api/sample-resume                  # returns resume.redacted.md content

GET    /                                    # serve frontend HTML
GET    /static/*                            # serve static assets
```

## 前端组件结构

按 Design.md 的卡片范式:

```
┌──────────────────────────────────────────────────────────────┐
│ top-nav: spike-mark + "Lyrebird"                             │  cream canvas
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  hero-band:                                                  │
│    h1 "Cognitive mechanism extraction"  (Cormorant 64/-1.5)  │  cream canvas
│    sub: "Six agents read your resume..."                     │
│                                                              │
│  ┌─ feature-card (cream surface-card) ──────────────────┐    │
│  │  RUN FORM                                            │    │
│  │  • Target role (text-input)                          │    │
│  │  • Resume textarea (text-input)                      │    │
│  │  • Interview turns (number)                          │    │
│  │  • Min incidents (number)                            │    │
│  │  • "Load sample resume" button-secondary             │    │
│  │  • "Start extraction" button-primary (coral)         │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
├──────────────────────────────────────────────────────────────┤  ← after submit
│                                                              │
│  product-mockup-card-dark:                                   │  dark surface
│    PIPELINE TIMELINE (7 stages, current highlighted)         │
│    AGENT ACTIVITY (rolling list with timings + tokens)       │
│    EVENT LOG (last N events, monospace)                      │
│                                                              │
│  ┌─ feature-card ──────────────────────────────────────┐     │
│  │ FINAL REPORT (when done)                            │     │
│  │ summary + validated/probable mechanisms             │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ footer: dark surface                                         │
└──────────────────────────────────────────────────────────────┘
```

## 不做的事

- 不做用户认证 (这不是产品系统, 是 demo)
- 不做多用户并发隔离 (RunRegistry 全局, 但 run_id 唯一所以也不会冲突)
- 不做 run 历史 (前端列表查看历史 run — 留给 V2)
- 不做断点恢复 (run.started 后进程重启就完全丢)
- 不做 LLM 流式输出 (我们的输出是结构化 JSON, 流式没意义)

## 验证策略

| 验证 | 方法 |
|---|---|
| EventBus 单元 | pytest, 模拟订阅/发射 |
| Pipeline 仍然能离线跑(无 bus) | 现有 69 个测试不动 + 新增"bus 为 None"测试 |
| API endpoint 形态 | FastAPI TestClient |
| SSE 实际流 | curl -N + sleep + 真实 run |
| 前端布局 | 启动 server, 浏览器打开, 视觉检查 |
| 端到端 web 流 | 真实跑一次, 截图存档 |

## 接下来分阶段

1. EventBus + Event schema + 单元测试
2. AgentContext 加入 bus + BaseAgent 发事件 + 现有测试仍 pass
3. Pipeline 发事件 + 新增 e2e bus 测试
4. FastAPI app + TestClient 测试
5. 前端 HTML/CSS/JS
6. 真实浏览器跑通
7. 写收尾 memo (08-09)

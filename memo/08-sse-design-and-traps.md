# SSE 实战:设计、坑、与三道防线

> 看似简单的 "服务器推事件给浏览器" 在生产化时有不少陷阱。这一篇把我们踩过的全部记下来。

## 为什么不是 WebSocket

需求是**单向**:服务端 → 浏览器,不需要全双工。SSE 比 WebSocket 简单一个数量级:
- 走标准 HTTP/1.1, 不需要 Upgrade 握手
- 浏览器原生 `EventSource` API, 零 JS 依赖
- 自动重连, 自动带 `Last-Event-ID`
- 协议人类可读, 可以用 `curl -N` 直接看
- 通过任何 nginx/防火墙/CORS 配置

代价: 单向。但我们就是单向。

## 我们的 SSE 协议形态

```
GET /api/runs/{run_id}/events HTTP/1.1
Accept: text/event-stream
Last-Event-ID: 42         <- 浏览器自动加,reconnect 时

HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache

event: stage.started
id: 43
data: {"seq":43,"type":"stage.started","payload":{"stage":"intake"},...}

event: agent.completed
id: 44
data: {"seq":44,"type":"agent.completed",...}

:ping                     <- sse-starlette 心跳, 每 15s 一次

event: run.completed
id: 88
data: {...}
```

关键设计要点:
- `event:` 字段 = 事件类型, 浏览器用 `addEventListener("agent.completed", ...)` 精准订阅
- `id:` 字段 = 单调 seq, 配合 Last-Event-ID 实现"断点续传"
- `data:` 字段 = JSON, 包含整个 Event 对象(便于前端 dedupe)

## 后端实现:线程池 + asyncio 桥

LLM SDK 是**同步**的 (`anthropic.messages.create()` 阻塞线程), FastAPI 默认是 async。两个世界要桥起来:

```python
# 在线程池里跑 Pipeline
future = self._executor.submit(pipeline.run, ...)

# 在 SSE handler 里用 asyncio.to_thread 包装同步队列
sub = h.bus.subscribe()       # 返回 queue.Queue
while True:
    ev = await asyncio.to_thread(sub.get, True, 1.0)
    yield {"event": ev.type.value, "data": ev.to_dict()}
```

`asyncio.to_thread` 把同步的 `queue.get` 包装成 awaitable, 不阻塞 event loop。这是 FastAPI 与同步 SDK 共存的标准模式。

## 三个坑 + 三道防线

### 坑 1: EventSource 自动重连 → 雪崩复制

**现象**: 一次 run 跑完, 前端 agent feed 出现 220 行(实际只有 11 次 LLM 调用), event log 出现 1040 行(实际 52 个事件)。

**根因链**:
1. Pipeline 跑完, 服务端发 `run.completed` 后关闭流
2. 浏览器 `EventSource` 不知道这是"正常结束", 当成断网, **自动重连**
3. 重连请求 `/events` 又触发 snapshot 全量回放
4. 客户端没去重, 每个事件再加一行 DOM
5. 服务端再关流 → 浏览器再重连... 20 次后才放弃

**三道防线** (任意一道生效就能阻止重复):

| 防线 | 位置 | 机制 |
|---|---|---|
| 1. 客户端主动关流 | `app.js` `handleEvent()` | 收到 `run.completed`/`run.failed` 立即 `src.close()` |
| 2. 客户端 dedupe by seq | `app.js` `handler()` | `if (data.seq <= seenSeq) return` |
| 3. 服务端读 `Last-Event-ID` 头 | `app.py` `stream_events()` | reconnect 时从 header 取 `last_event_id`, 跳过已发的 |

**为什么三道**:浏览器实现差异、缓存策略、网络中断都可能让其中一道失效。三道独立 + 互相 fallback 是工程稳定性的标配。

我把"重连后不应得到重复事件"写成了 `test_sse_replay_honors_last_event_id_header` 回归测试, 锁死这个行为。

### 坑 2: 同毫秒 run_id 碰撞

**现象**: `test_list_runs` 偶发失败 — POST 两次但 `GET /api/runs` 只返回 1 条。

**根因**: `run_id` 用 `datetime.now().strftime(...)[:-3]` 截到毫秒。Python 3.14 + TestClient 两次 POST 在同毫秒内, ID 碰撞, 后者覆盖前者。

**修复**: 加单调计数器后缀。format = `run_YYYYMMDD_HHMMSS_mmm_NNNN`, 微毫秒级也保证唯一。

**通用教训**: 任何 "based on timestamp" 的 ID, 高频场景下都要带 tiebreaker。永远不要相信"两次调用之间一定差几 ms"。

### 坑 3: HTML `hidden` 被 CSS `display: flex` 覆盖

**现象**: 我用 `<section hidden>` 标记观测面板, JS 在 run 启动时 `el.hidden = false` 来显示。但截图发现初始页面**就显示了**观测面板。

**根因**: 浏览器默认的 `[hidden] { display: none }` 在 user-agent 层。我的 `.observability-band { display: flex }` 在 author 层, 同等特异度, author 层后写 winning。所以 `hidden` 不起作用。

**修复**: 一行 CSS:
```css
[hidden] { display: none !important; }
```

把 `!important` 加到 hidden 规则, 让它在所有 author 类规则之上。

**通用教训**:`hidden` HTML 属性的 UA 默认规则可以被任何同特异度 author 规则覆盖。如果项目里有 `display: flex/grid` 应用在可隐藏的元素上, 务必加 `[hidden] !important` 强制规则。

## 静态资源版本号

```html
<link rel="stylesheet" href="/static/styles.css?v=3" />
<script src="/static/app.js?v=3"></script>
```

为什么手动 bump:
- 浏览器对 `/static/*.css` 做长缓存(StaticFiles 默认 ETag)
- `Ctrl+R` reload 不重新拉外部子资源(CSS/JS), 除非 URL 变了
- 部署 hash 是工程化的, 但我们简单做: 改一次资源就 bump 一次

生产化建议:
- 用 webpack/vite 的内容 hash → 自动 cache-bust
- 或在 FastAPI 启动时算 file mtime/hash, 注入到模板

## 心跳

`EventSourceResponse(event_gen(), ping=15)` 让 sse-starlette 每 15 秒发一个 `:ping` 注释行。

为什么需要:
- 浏览器某些代理 / nginx default config 会在 60s 无数据后关连接
- nginx `proxy_read_timeout` 默认 60s
- 心跳让中间层"看到字节流", 不会误判为僵尸连接

注释行不触发任何 `addEventListener`, 客户端完全不感知。

## 客户端单流约束

```js
let currentStream = null;

function openStream(runId) {
    if (currentStream) {
        try { currentStream.close(); } catch (_) {}
    }
    currentStream = new EventSource(...);
}
```

一个页面只能有一个活跃流。点击"Start another extraction"重新跑时, 先关老的, 再开新的。否则浏览器会同时跑两条 SSE, 旧的还在往 DOM 写。

## 观测体系的最小 API 覆盖

如果你只能保留 3 个 API endpoint 来支撑"实时观测 + 历史回看", 必须是这三个:

| Endpoint | 用途 | 客户端时机 |
|---|---|---|
| `POST /api/runs` | 启动 + 拿 run_id | 用户点 Start |
| `GET /api/runs/{id}/events` (SSE) | 实时流 | 启动后立即订阅, 直到 terminal |
| `GET /api/runs/{id}/snapshot` | 全量快照 | 页面刷新 / 加入已有 run / 调试 |

加分项 (但不是必须):
- `GET /api/runs/{id}/report` — 终态产物
- `GET /api/runs` — 列表 (历史回看)
- `POST /api/runs/{id}/cancel` — 主动停止 (我们暂未实现, 留 V2)

`snapshot` 和 `events` 的关系: snapshot 是 "至此为止所有事件", events 是 "从此向后所有事件"。客户端可以选择:
- 先 `snapshot(after_seq=0)` 一次性获取历史
- 然后 `events(last_event_id=snapshot.maxSeq)` 接住后续

这是标准的"replay + tail"模式, 与 Kafka consumer 的 seek+poll 是一回事。

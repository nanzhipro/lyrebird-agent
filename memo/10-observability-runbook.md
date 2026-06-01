# 观测体系 Runbook (V0.2)

> 给后来运维 / 二次开发的人。一切关于"怎么启动、怎么调试、怎么扩展"的操作型知识在这里。

## 启动 web server

```bash
source .venv/bin/activate
uvicorn lyrebird.web.app:app --host 127.0.0.1 --port 8765 --reload
```

`--reload` 仅在开发模式启用 (代码改动后自动重启)。生产部署不要加。

成功后访问 http://127.0.0.1:8765/ 应看到表单页。

## 关键 URL 地图

| URL | 用途 |
|---|---|
| `/` | 主页 (form + observability + report) |
| `/static/styles.css?v=N` | 设计系统 CSS |
| `/static/app.js?v=N` | 前端控制器 |
| `/docs` | FastAPI 自动 OpenAPI 文档 (Swagger UI) |
| `/redoc` | OpenAPI 文档 (ReDoc 风格) |
| `/healthz` | 健康检查 |
| `/api/sample-resume` | 拿样本简历 |
| `/api/runs` POST | 启动 run |
| `/api/runs` GET | 列出活跃 + 近期 run |
| `/api/runs/{id}` | run 元数据 + 状态 |
| `/api/runs/{id}/events` | **SSE 事件流** |
| `/api/runs/{id}/snapshot` | 事件全量快照 |
| `/api/runs/{id}/report` | 终态报告 |

## 调试三件事

### 看 SSE 流(不用浏览器)

```bash
# 启动一个 run
RUNID=$(curl -s -X POST http://127.0.0.1:8765/api/runs \
  -H 'content-type: application/json' \
  -d "$(python3 -c 'import json; print(json.dumps({
    "resume_text": open("resume.redacted.md").read(),
    "target_role": "macOS 终端安全架构师",
    "candidate_id": "cand_debug",
    "turns": 3, "min_incidents": 2,
  }))')" | python3 -c "import sys,json;print(json.load(sys.stdin)['run_id'])")
echo "started: $RUNID"

# 追 SSE 流 (Ctrl-C 退出)
curl -N -s "http://127.0.0.1:8765/api/runs/$RUNID/events"
```

每个事件长这样:
```
event: stage.started
id: 12
data: {"seq":12,"run_id":"...","timestamp":"...","type":"stage.started","payload":{"stage":"intake"}}
```

### 看历史 snapshot

```bash
curl -s "http://127.0.0.1:8765/api/runs/$RUNID/snapshot" | python3 -m json.tool | head -40
```

`?after_seq=N` 可以过滤只看 N 之后的事件。

### 看 transcript 文件

每次 run 终态(成功或失败)后, 完整 transcript 写到 `runs/{run_id}.json`:

```bash
ls -la runs/
cat runs/run_*.json | python3 -m json.tool | less
```

字段:
- `params` — 启动参数
- `events` — 全部事件
- `report` — 最终 ExtractionReport
- `gates` — 5 道门控结果
- `llm_stats` — token 总计

## 常见故障模式

### "DEEPSEEK_API_KEY not set in env"

`.env` 文件没在工作目录, 或 key 错。验证:
```bash
python3 -c "from dotenv import load_dotenv; load_dotenv(); import os; print('key set:', bool(os.environ.get('DEEPSEEK_API_KEY')))"
```

### Run status 长时间 stuck 在 "running"

检查 uvicorn 日志:
```bash
tail -f /tmp/lyrebird-uvicorn.log
```

通常是 LLM 调用超时, 或者 schema 验证失败循环重试。修复在客户端 / SDK 层, 不在 web 层。

### 浏览器看到陈旧 CSS / JS

bump `index.html` 里的 `?v=N` 版本号。重启不需要。

### SSE 流没有任何事件

最可能是: `last_event_id` 已经追上最新事件。检查:
```bash
curl -s "http://127.0.0.1:8765/api/runs/$RUNID/snapshot" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'status: {d[\"status\"]}, n_events: {len(d[\"events\"])}, terminal: {d[\"status\"] in (\"completed\",\"failed\")}')
"
```

如果 status=completed, SSE 流会**立即关闭**(没新事件可流), 这是正常的。前端在收到 `run.completed` 后也应立即关流(我们做了)。

### Pipeline 抛异常 → run.failed

```bash
curl -s "http://127.0.0.1:8765/api/runs/$RUNID" | python3 -m json.tool
```

看 `error` 字段。常见:
- `RuntimeError: sufficiency-gate failed: ...` — Intake 没找到 high-priority hypothesis
- `RuntimeError: complete_json exhausted 3 retries` — LLM 多次返回不合 schema

## 扩展指南

### 加新的事件类型

1. 改 `src/lyrebird/observability.py`, 给 `EventType` 加一项 (例:`MEMORY_WRITTEN = "memory.written"`)
2. 改 Pipeline 或 Agent, 在合适位置 `bus.emit(EventType.MEMORY_WRITTEN, ...)`
3. 改前端 `app.js`, 在 `addEventListener` 数组里加 `"memory.written"`
4. 改 `handleEvent` switch, 加该类型的 DOM 更新逻辑

注意客户端 SSE 监听是**精确字符串匹配**, 必须把新类型字符串加到 `addEventListener` 数组, 不然会被静默丢弃。

### 加新的 stage

1. 改 `src/lyrebird/agents/orchestrator.py` 的 `Pipeline.run()`, 加新 stage 块, 用 `_enter_stage` / `_exit_stage` 包裹
2. 改前端 `app.js` 的 `STAGES` 常量, 按出现顺序加新条目
3. 不需要改后端 schema, stage 名是字符串

### 加 cancel 功能

我们暂未实现 (`POST /api/runs/{id}/cancel`)。设计草图:
1. Pipeline 加一个 `threading.Event` 作为 cancel flag
2. 每个 stage 入口检查 flag, `bus.emit(RUN_FAILED, error="cancelled")` 后 raise
3. API endpoint 设置 flag, 等线程退出 (或不等, async)
4. 前端 "Cancel" 按钮 → POST → 显示 "cancelling…"

### 加多用户隔离

V0.2 是单租户。多租户最少改动:
1. POST /api/runs 加 `user_id` 参数 + JWT 鉴权 (FastAPI Depends)
2. RunRegistry 用 `(user_id, run_id)` 复合 key
3. SSE / report endpoint 校验 user_id

或者更简单: 给每个用户独立的 RunRegistry 实例, 用 sub-app mount。

## 性能预算 (单 user, MVP)

| 资源 | 上限 (经验值) |
|---|---|
| 同时 run | `RunRegistry.max_concurrent_runs=4` |
| 单 run 时长 | 6-turn ≈ 90s, 3-turn ≈ 45s |
| 单 run token | 6-turn ≈ 25k, 3-turn ≈ 13k |
| 内存 | 一个 RunHandle ≈ 几十 KB; 历史保留 1h 后驱逐 |
| 文件 IO | 每 run ≈ 30-50 个 artifact JSON + 1 个 transcript |

如果你想扩到 10 个并发 user, 调 `max_concurrent_runs` 即可, 不需要重新架构。

## 部署到 production 的最小修改清单

如果你要把这个 demo 上生产:

1. **去掉 `--reload`**, 用 `--workers N` 多 worker (但注意: in-memory RunRegistry 不能跨 worker)
2. **CORS** — 加 `CORSMiddleware` 限制域名
3. **鉴权** — POST /api/runs 加 token 校验
4. **持久化 Registry** — 当前进程重启 = 活跃 run 丢失。改造为读 transcript + Redis 队列
5. **静态资源** — 用 CDN 或 nginx serve, FastAPI 不擅长
6. **观测** — 加 `/metrics` (Prometheus), 否则 SSE 连接数无法监控
7. **资源隔离** — `RunRegistry.max_concurrent_runs` 接 OS-level (cgroup) 或 RQ/Celery 队列

不在 MVP scope, 但 V2 必做。

## V0.2 已知限制

- 无认证, 任何能访问端口的人都能跑 run (烧 API key)
- 进程重启 → 活跃 run 状态丢失 (transcript 在磁盘上但页面不显示)
- 没有 run 列表 UI (API 有, 前端没渲染)
- 没有 cancel 按钮
- 没有 dark mode (整个设计系统是 cream-first)
- 大屏幕 (> 1440px) 没有额外利用空间, container max-width=1200 锁死

# Runbook — 给后来者的操作手册

## 一次性 setup

```bash
cd lyrebird-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # 或: pip install -e .  + 单独装 pytest pytest-asyncio
```

确保 `.env` 文件存在:

```
# Anthropic API base_url: https://api.deepseek.com/anthropic
DEEPSEEK_API_KEY=sk-...
```

## 跑测试 (不烧 API)

```bash
pytest
```

应看到 **69 passed, 1 skipped**。skipped 的是 E2E 真实 API smoke。

## 跑 E2E 真实 API smoke (烧约 10–20k token)

```bash
LYREBIRD_E2E=1 pytest tests/test_pipeline_e2e.py
```

## 端到端运行 (产出报告)

```bash
python -m lyrebird.main \
  --resume resume.redacted.md \
  --target-role "macOS 终端安全架构师" \
  --turns 6 \
  --min-incidents 3
```

参数:
- `--resume` 必填, 简历 markdown 文件路径
- `--target-role` 可选, 推荐写, 影响 Intake 的关注角度
- `--turns` 默认 6, 推荐 6–8 (≤4 容易触发 evidence_gate 软失败)
- `--min-incidents` 默认 3, evidence_gate 的最小事件数
- `--verbose` 打开 DEBUG 日志

产物:
- `runs/run_YYYYMMDD_HHMMSS.json` — 完整 transcript
- `artifacts/{candidate_profile,interview_turn,evidence_card,mechanism_card,review_findings,extraction_report}/*.json` — 单条 artifact + .prov.json 出处审计

## 看一次运行的结果

```bash
python -c "
import json
data = json.load(open('runs/<file>.json'))
print(json.dumps(data['report'], ensure_ascii=False, indent=2))
"
```

## 调试常见问题

### `complete_json` 反复重试

打开 `--verbose`, 看 raw response。99% 是模型把 markdown 围栏带进来了, 或 `generated_at` 给了空串。schema 已经有兜底 validator, 一般会过。

### evidence_gate 软失败

意味着 6 轮里 critical_incident 太少。三个原因之一:
1. 候选人(simulated 或真人)答得抽象, 没具体事件
2. interviewer 没切换 hypothesis
3. evidence_mapper 合并太激进

可尝试: 增加 `--turns 8`, 或检查 `simulated_candidate` 的 persona 是否需要再严。

### 所有机制都被降级到 hypothesis

意味着 Skeptic 找到了 HIGH severity 问题, orchestrator 按规则降级。这是**正常**, 不是 bug。要么补更多 evidence, 要么接受"目前证据强度只到 probable"。

### Pydantic 报错

最常见的是 schema 不严: 比如新加字段忘了 default。schema 改后先跑 `pytest tests/test_schemas.py`。

## 改造方向

| 想做 | 改哪里 |
|---|---|
| 换底层模型 (Anthropic / Mistral) | `src/lyrebird/llm/client.py` 里改 `base_url` + `_MODEL_MAP` |
| 加一个新 Agent | 新建 `src/lyrebird/agents/<name>.py`, 在 `Pipeline.run()` 里插一个 stage |
| 改提问策略 | 改 `skills/incident-probing/SKILL.md` (不用动代码) |
| 改命名风格 | 改 `skills/mechanism-taxonomy/SKILL.md` |
| 改报告模板 | 改 `skills/report-authoring/SKILL.md` |
| 收紧/放宽门控 | `src/lyrebird/agents/orchestrator.py` 里改 `*_gate()` 函数 |
| 增加 PII 类型 | `src/lyrebird/validators/pii_guard.py` 加正则 |
| 接入数据库 | 把 `ArtifactStore` 的 file IO 换成 ORM |

## 复盘 + 提升

每次跑完, 看三个东西:
1. **evidence 多样性** — 4 张 evidence 是否落在 ≥3 个不同 experience_id
2. **mechanism 命名质量** — 是不是动宾结构, 有没有"能力/思维/力"后缀
3. **Skeptic 是否真的找了问题** — 全是空 findings 才该警觉 (说明它没干活)

如果连续多次 Skeptic 都给 `findings: []`, 八成是 prompt 漂了, 需要回头改 `skills/skeptic-checklist/SKILL.md`。

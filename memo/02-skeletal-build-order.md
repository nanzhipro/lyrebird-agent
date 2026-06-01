# 构建顺序: 为什么这样分层

Multi-Agent 系统极容易写成"一个大循环里塞五个 if-else"。本系统按以下顺序自底向上构建,**任何一层失败都不会污染上层**:

```
Layer 0  pyproject.toml + venv + pytest 跑通
Layer 1  schemas.py (Pydantic)           ← 不依赖任何外部
Layer 2  llm/client.py (DeepSeek-Anthropic) ← 仅依赖 Pydantic
Layer 3  validators/* (PII, citation, confidence) ← 依赖 Layer 1
Layer 4  artifact_store.py ← 依赖 Layer 1
Layer 5  skills.py + skills/*/SKILL.md ← 文件系统层, 不依赖代码
Layer 6  agents/base.py + 6 个 agents/*.py ← 依赖 Layer 2/4/5
Layer 7  agents/orchestrator.py ← 依赖所有
Layer 8  main.py (CLI) ← 顶层组装
```

## 为什么从 schemas 开始

因为 Pydantic schema 是这个系统的**事实标准**:
- LLM 输出要符合它(complete_json)
- ArtifactStore 把它写盘
- 验证器读它来打分
- 报告生成器返回它

**所有"模型说了什么"在跨过 schema 之前都不算数。** 这把 LLM 的不确定性收敛到一个明确边界。

## 为什么 LLM Client 在 Validators 之前

因为 `complete_json` 已经在 client 内部做了第一道 schema 校验。如果 LLM 客户端没写好, validators 测试都跑不到。

## 为什么 Skills 是文件而不是字符串

`SKILL.md` 是带 frontmatter 的 markdown 文件, 这样:
- 可以用 git 管理变更
- 可以独立 review
- 不需要重新部署代码就能改提问策略
- arch.md 强调的 "progressive disclosure" 一目了然 — 元数据扫一遍, body 按需读

## 为什么 Orchestrator 不是 Agent

它**不调用 LLM**, 只做:
- 状态机切换
- artifact 读写
- gate 判断 (gate 函数都是纯 Python)
- 基于 Skeptic 输出**确定性地**调整 confidence 和 status

按 arch.md §架构原则二, "PII 检测、schema 校验、置信度计算、引文覆盖检查、报告模板装配,都应优先做成确定性组件"。Orchestrator 就是这些确定性组件的胶水。

## TDD 节奏

每个 Layer 的 commit 都是:
1. 写 `tests/test_<layer>.py` (失败)
2. 写最小实现 (通过)
3. 跑 `pytest`
4. 写 memo 说"为什么这层这样设计"
5. 进入下一层

| Layer | Tests | 失败时影响 |
|---|---|---|
| schemas | 13 | 全系统数据流崩 |
| llm/client | 11 | 调不通 DeepSeek |
| validators | 13 | 门控失效 |
| artifact_store | 6 | 跨 Agent 通信废 |
| skills | 4 | Agent 没指引 |
| agents (offline) | 7 | Agent 装配错 |
| orchestrator | 14 | 状态机错 |
| **总计** | **68** + 1 E2E | — |

测试覆盖率不是"行覆盖率", 而是**每个业务规则都有一个 test**。例如:
- `test_mechanism_card_requires_evidence` 锁死了"命名门"
- `test_apply_review_downgrades_validated_on_high_severity` 锁死了"一致性门"
- `test_publish_gate_requires_evidence_on_validated_claims` 锁死了"发布门"

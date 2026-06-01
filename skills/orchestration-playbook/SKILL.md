---
name: orchestration-playbook
description: Use when coordinating the seven-stage extraction pipeline. Tells the Orchestrator when to delegate, when to gate, when to escalate.
when_to_use: Triggered by the Orchestrator at every state transition.
---

# 编排剧本 (Orchestration Playbook)

## 七阶段时间线

```
1. consent           → 候选人同意 + 边界确认
2. intake            → Intake Agent: resume → CandidateProfile + Hypotheses
3. interview         → Interviewer Agent: 关键事件追问 (多轮)
4. evidence_mapping  → Evidence Mapper: 把每轮对话变成 evidence_card
5. mechanism_naming  → Mechanism Modeler: evidence_cards → mechanism_cards
6. skeptic_review    → Skeptic Agent: 反驳与降级
7. publish           → Report Composer: extraction_report
```

## 委派规则

| 何时委派 | 何时**不**委派 |
|---|---|
| 任务需要并行处理多个独立证据面向 | schema 校验 (走 validator) |
| 任务需要独立上下文避免污染 | PII 检测 (走 validator) |
| 任务需要独立的反驳或独立命名 | 置信度计算 (走 confidence_scorer) |
| 任务输出可结构化为 schema | 引文回链检查 (走 citation_checker) |

## 门控规则

### 充足性门 (intake → interview)
- 至少 1 个 hypothesis 的 priority = high
- candidate_profile 必须有 >= 1 个 core_experience

### 证据门 (interview → mechanism_naming)
- 必须 >= 3 张 evidence_card (型 critical_incident)
- 每张 critical_incident 都必须有 cues + judgment + actions + outcome

### 命名门 (mechanism_naming → skeptic_review)
- 每个 mechanism_card 必须有 >= 2 张 distinct evidence_ids
- 至少 1 张 evidence 来自对话, 不能全是 resume_claim

### 一致性门 (skeptic_review → publish)
- Skeptic 找到的 `high` severity findings 必须有 repair_actions 处理
- 若 Skeptic 找到未解决的强反例, 该机制 status 强制 = probable, 不允许 validated

### 发布门 (publish → done)
- 报告中任何 ValidatedMechanism 必须有 evidence_ids
- PII Guard 扫描通过 (或所有 finding 已被 redact)

## 阶段失败时的回退

| 失败 | 回退 |
|---|---|
| 充足性门: hypothesis 不足 | 触发 Intake 重新解析, 用更细颗粒度 |
| 证据门: incident 数不足 | 继续 interview, 把 hypothesis 优先级最高的换一个角度问 |
| 命名门: 机制全部只支撑 1 张证据 | 触发 Mechanism Modeler 重新聚类, 若仍不足则降到 hypothesis |
| 一致性门: Skeptic 无法消除高严重度问题 | 强制降级为 probable; 若 confidence < 0.4, 移到 needs_more_evidence |
| 发布门: PII 未清理 | redact 后重试, 不允许跳过 |

## 输出契约

Orchestrator 在每个阶段切换时只输出:
- 当前阶段
- 已确认事实 (artifact_ids)
- 未解决问题
- 下一步委派任务 (task_brief)

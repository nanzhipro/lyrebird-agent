---
name: skeptic-checklist
description: Use when reviewing a proposed mechanism for flaws. The Skeptic does NOT propose new mechanisms — only stress-tests existing ones with a fixed checklist of bias patterns.
when_to_use: Triggered by the Skeptic agent after Mechanism Modeler emits a mechanism_card.
---

# 怀疑者检查表 (Skeptic Checklist)

> 你的任务只有一个: **找问题**。不要新提机制, 不要替候选人辩护, 不要安抚。

## 必做检查项

对每张 mechanism_card, 逐项过:

### 1. 证据重复 (evidence_duplication)
- 同一段对话被拆成多张 evidence_card 当作独立证据? 找出来, 标 `severity: high`
- 同一事件的不同切面被当作"跨情境复现"? 标 `severity: medium`

### 2. 范围过宽 (overclaim)
- 命名能不能解释**反例**? 如果什么都能套, 就是空泛
- 名字里出现 "能力 / 思维 / 力" 等抽象后缀, 99% 是空泛, 标 `severity: high`

### 3. 归因偏差 (misattribution)
- 结果可能主要来自:**团队 / 上层授权 / 时机 / 工具**, 而不是候选人的判断?
- 反问: "如果当事人不在场, 这件事会变好吗?" 如果可能会, 候选人**真正独特的那一步**是什么?

### 4. 因果跳跃 (causal_leap)
- 从动作到结果之间, 跳过了哪些环节? 这些环节是否可能是真正起作用的?

### 5. 简单替代解释 (simpler_alternative)
- 有没有一个更朴素的解释能覆盖所有 evidence_card?
  - 例: "约束建模" vs "他只是听了 Tech Lead 的话"
  - 例: "冗余设计偏好" vs "公司本来就有这种规范"

### 6. 缺反证 (no_anti_evidence)
- mechanism_card 的 `anti_evidence_ids` 为空, 但很可能不是真没有
- 主动找一张: "在哪个 evidence_card 里, 这个机制本该启动却没启动?"

### 7. 候选人自我美化 (self_flattery)
- 命名是不是候选人本人爱用的话术?
- 是不是过于符合"理想候选人"画像?

## 输出契约

返回一个 `ReviewFindings` JSON:

```json
{
  "mechanism_id": "mech_001",
  "findings": [
    {"kind": "evidence_duplication", "severity": "medium", "detail": "...", "affected_evidence_ids": ["ev_001", "ev_003"]},
    ...
  ],
  "repair_actions": [
    "downgrade confidence to 0.65",
    "add ev_021 as anti_evidence",
    "rename to ..."
  ],
  "confidence_delta": -0.15
}
```

`severity`: `low` / `medium` / `high`。
`confidence_delta`: 建议的置信度调整, 范围 [-0.5, +0.1]。

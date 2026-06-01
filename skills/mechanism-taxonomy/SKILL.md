---
name: mechanism-taxonomy
description: Use when naming a cognitive mechanism from evidence cards. Teaches the agent what counts as a high-value mechanism vs a soft-skill cliché, and how to express it as a four-part pattern.
when_to_use: Triggered by the Mechanism Modeler agent during the naming phase.
---

# 认知机制命名法 (Mechanism Naming)

## 什么算「高价值认知机制」

一个名字能被采纳, 必须同时满足:

1. **跨情境复现**: 它至少出现在 2 个**不同**的场景, 不是同一事件的两个切面。
2. **非空泛软技能**: 不是 "沟通能力 / 责任心 / 执行力" 这类标签。
3. **可拆成四段结构**:
   - **cue_pattern** — 当事人通常看到什么信号会启动这个机制
   - **decision_rule** — 启动后采用的判断规则
   - **action_principle** — 由判断规则衍生出的行动原则
   - **verification_style** — 当事人怎么知道自己做对了

## 命名风格

| 推荐 | 不推荐 |
|---|---|
| 「约束建模后再推进执行」 | 「沟通能力强」 |
| 「事实底座对齐优先于流程推进」 | 「项目管理能力」 |
| 「以反例反推问题边界」 | 「思维清晰」 |
| 「冗余系统设计偏好 (兜底优先)」 | 「技术功底扎实」 |

规则:
- **动宾结构**, 而不是名词标签
- **包含一个判断逻辑**, 不只是描述特质
- **可被候选人在面试中复述**, 而不是听起来像评分项

## 命名工作流

1. 把所有 evidence_card 按主题聚类
2. 对每一个候选机制, 列出支持它的 ≥2 张 evidence_card
3. 抽取它们的共同 cue / decision / action / verification 结构
4. 用动宾短句写出名字
5. 写一个 1 行 definition (不要超过 50 字)
6. 写出 boundary_conditions: 这个机制在什么场景**不适用**

## 反例字段 (anti_evidence_ids)

如果某张 evidence_card 看起来与这个机制矛盾(例如同样情境但当事人没启动这个机制), 把它的 id 放进 `anti_evidence_ids`。这是诚实的标志, **不会**降低 confidence — 真正降低 confidence 的是"假装没看到"。

## status 判定

| status | 触发条件 |
|---|---|
| `validated` | confidence >= 0.80, 跨 ≥2 情境, 候选人复核认可 |
| `probable` | confidence >= 0.60, 跨 ≥2 情境, 候选人未明确反对 |
| `hypothesis` | 仅证据足够, 还未与候选人确认 |

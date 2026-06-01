---
name: evidence-schema
description: Use when compressing a candidate's narrative into a structured EvidenceCard. Teaches the agent the field semantics, what counts as a critical_incident vs resume_claim, and when to mark insufficiency.
when_to_use: Triggered by the Evidence Mapper agent after each interview turn or at end of intake.
---

# 证据卡结构化萃取 (EvidenceCard schema)

## 字段语义

| 字段 | 含义 | 抽取规则 |
|---|---|---|
| `situation` | 当时的情境, 一句话 | 用候选人原话提炼, 不加修饰词 |
| `goal` | 候选人当时想达成的目标 | 必须是当时的目标, 不是事后的目标 |
| `constraints` | 当时存在的硬约束 | 列出 1-4 个, 时间/资源/合规/组织依赖 |
| `cues` | 候选人观察到的、用于判断的信号 | 这是**最重要**的字段; 如果空白, 应标 insufficiency |
| `judgment` | 候选人当时的因果解释 | 一句话: "我当时认为 X, 因为看到 Y" |
| `actions` | 实际做的动作, 按时间顺序 | 列出 2-5 步; 不要写"沟通"这种动词, 要写具体动作 |
| `outcome` | 实际结果 | 写客观结果, 不写"很成功" |
| `confidence` | 这张卡的可信度 | 见下表 |

## 证据类型 (type) 判定

| 值 | 触发条件 |
|---|---|
| `critical_incident` | 来自对话中讲述的具体一次事件, 有时间、有动作 |
| `resume_claim` | 仅来自简历, 没有对话佐证 |
| `self_assessment` | 候选人对自己的笼统评价, 无具体事件 |

## confidence 打分基线

| 分数 | 触发条件 |
|---|---|
| 0.80–0.95 | critical_incident, cues + judgment + actions + outcome 齐全 |
| 0.60–0.79 | critical_incident, 缺 1 项关键字段 |
| 0.40–0.59 | resume_claim, 但与对话能粗略对上 |
| 0.20–0.39 | self_assessment 或大量缺口 |
| <0.20 | 几乎只有标签 |

## insufficiency_reason 何时填

只要 confidence < 0.6, 必须填一个简短理由, 例如:
- `"missing_cues"` — 候选人没说看到什么信号
- `"outcome_unclear"` — 不知道结果如何
- `"attribution_ambiguous"` — 分不清是个人贡献还是团队
- `"self_assessment_only"` — 只有自评

## 一致性规则

- 不得发明 outcome
- 不得把"候选人的自我评价"当成 critical_incident
- 同一段对话只能产出 1 张 EvidenceCard, 除非候选人主动展开了第二个独立事件
- `source_ref.conversation_turn_ids` 必须能回指到真实的 turn id

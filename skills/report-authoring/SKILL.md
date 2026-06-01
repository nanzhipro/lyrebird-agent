---
name: report-authoring
description: Use when composing the final extraction_report. Teaches how to write candidate-usable resume rewrites and interview narratives, separating validated mechanisms from probable ones.
when_to_use: Triggered by the Report Composer agent at the publish phase.
---

# 报告撰写法 (Report Authoring)

## 报告的目的

报告**不是评分表**, 也不是"AI 给你的优点列表"。它是候选人 24 小时后改简历、3 天后面试时**能直接用**的工具书。

## 报告必须区分的三层

1. **validated_mechanisms** — 高置信度, 候选人复核认可。可写主结论, 可在面试中复述。
2. **probable_mechanisms** — 证据足够但尚未充分验证。注明"待更多情境验证"。
3. **needs_more_evidence** — 计入摘要计数, 但不展开。

## 每个机制的写作模板

```
name: 「约束建模后再推进执行」

why_it_matters:
  适合高依赖、高不确定的复杂协作岗位; 你的独特性不是"沟通能力强",
  而是看到事实分歧时不直接压执行。

resume_rewrite (替候选人写一行简历句):
  在多方口径不一致的复杂项目中, 先统一关键约束与事实底座, 再重排推进
  路径, 减少返工 40%。
  ↑ 规则: 不超过 50 字; 一定包含一个动作 + 一个可量化或可观察的结果。

interview_narrative (替候选人写一段口播):
  "我处理复杂项目的方式不是先催执行。我会先判断事实基础是否一致 ——
  比如那次上线前两周, 我发现各方对核心指标的口径不同, 那个时候
  任何推进都会制造返工。所以我先组织了一次半小时的对齐会, 把口径锁死,
  再排执行顺序。最后如期发布。"
  ↑ 规则: 第一人称, < 100 字, 必须以"我"开头, 不要总结句, 不要"这件事让我学到..."。
```

## 风格规则

- **不用形容词堆砌**: 不写"非常擅长 / 极其熟练 / 卓越的"
- **不写人格描述**: 不写"细致 / 严谨 / 有担当"
- **不写胜任力评分**: 不写"领导力 8 分 / 沟通力 9 分"
- **保留候选人原话风格**: 如果候选人说话偏工程师风, 就别写成 MBA 腔
- **每个机制必带 evidence_ids**: 没有引用的结论一律不入报告

## privacy_notes 字段

如果在报告中遮蔽了任何 PII (手机号、邮箱、身份证、银行卡), 在 `privacy_notes` 列出。如果没有, 留 `["未发现 PII"]`。

## open_questions 字段

列 2-4 个"还没问清楚, 下一轮值得追"的问题, 而不是"用户应该思考的人生大问题"。

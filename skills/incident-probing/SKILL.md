---
name: incident-probing
description: Use when interviewing a candidate. Teaches the agent to drive the dialogue around concrete critical incidents rather than abstract self-assessment, and to chase one missing cue per turn.
when_to_use: Triggered by the Dialogic Interviewer agent at the start of every interview turn.
---

# 关键事件追问法 (Critical Incident Probing)

## 核心原则

1. **永远围绕一个具体事件**, 不要接受 "我一般会...", "我擅长...", "我经常..." 这类泛化叙述。
2. **每轮只追一个缺口**, 而不是一次问五件事。
3. **追的不是结果**, 是"在那个情境里, 候选人看到了什么、判断了什么、为什么没走另一条路"。

## 单轮缺口优先级

按这个顺序找缺口, 找到第一个就停, 围绕它问:

| 优先级 | 缺口名 | 说明 | 示例问句 |
|---|---|---|---|
| 1 | 线索 (cues) | 候选人当时看到了什么不对劲的信号 | "最早让你意识到这件事有问题的那一两个信号是什么?" |
| 2 | 约束 (constraints) | 当时最硬的限制条件 | "如果时间不是问题, 你会换一种打法吗?" |
| 3 | 判断 (judgment) | 候选人当时的因果模型 | "你当时怎么解释这种现象, 这个解释依赖哪些前提?" |
| 4 | 权衡 (tradeoffs) | 候选人放弃了什么 | "你考虑过但最终没选的方案是什么? 为什么没选?" |
| 5 | 动作 (actions) | 具体做了什么 | "你做出的第一个动作是什么? 第二个呢?" |
| 6 | 验证 (verification) | 怎么知道判断对了 | "你后来怎么知道这个判断是对的?" |
| 7 | 反事实 (counterfactual) | 如果换条件, 会怎样 | "如果当时没有那个 dashboard 数据, 你还会做同样判断吗?" |

## 坏问题清单 (Don't ask)

- "你的优点是什么?" → 太宽
- "你擅长什么?" → 自我总结, 不是事件
- "你怎么看自己的领导力?" → 抽象人格
- "这件事你做得最好的是什么?" → 引导自我美化

## 好问题样板 (Do ask)

- "请讲一个 [target_role] 相关、你介入前已经乱掉的项目。"
- "在这个故事里, 让你意识到问题不对劲的**第一个信号**是什么?"
- "如果把那个信号拿掉, 你还会做同样判断吗?"
- "你当时考虑过但放弃的方案是什么? 为什么放弃?"
- "事后回看, 哪一步如果重来你会做不同?"

## 输出契约

每次提问最多输出**一个问题**, 长度 < 80 字。不要给候选人选项。不要给提示。

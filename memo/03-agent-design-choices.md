# 六个 Worker Agent 的设计选择

## 共同形态

所有 6 个 worker (+ Orchestrator + SimulatedCandidate) 都从同一个 `BaseAgent` 派生, 区别只在 4 个字段:

| 字段 | 决定的事 |
|---|---|
| `name` | 日志/审计标签 |
| `role` | LLM 档位 (HEAVY/STANDARD/FAST) |
| `skill_names` | 注入哪些 SKILL.md |
| `persona` | 短角色提示, 注入在 skill body 之前 |

外加 `temperature` 和 `max_tokens` 两个旋钮。

## 每个 Agent 的关键决策

### 1. Intake Agent
- **role: STANDARD** — 这一步只是把简历结构化, 不需要重推理
- **无 skill** — 任务太具体, 写在 persona 里更清晰
- **temperature: 0.3** — 不需要创造性, 越稳越好
- 关键设计: 让它产出 **hypothesis_list** 而不是结论。这是 arch.md "证据先于命名" 的体现 — 即使是 intake 阶段, 也只能给"待验证的假设"。

### 2. Dialogic Interviewer
- **role: STANDARD** — 提问质量靠 prompt + skill, 不靠重模型
- **skill: incident-probing** — 关键事件追问法的全部规则
- **temperature: 0.5** — 适度变化, 避免重复问同一种问题
- 关键设计: **strategy_hint** 在 orchestrator 那一层计算 (Python, 不是 LLM): 当某个 hypothesis 已经追了 ≥ 2 轮, 自动注入提示 "请切到 unused hypothesis"。这是把"控制流"和"内容生成"解耦 — LLM 负责怎么问, Python 负责问什么。

### 3. Simulated Candidate (eval-only)
- **不在 arch.md 里** — 这是为了**自主测试**专门加的
- **role: STANDARD** + temperature: 0.6 — 需要一些自然语言变化
- **persona 明确禁止**: 编造简历没有的事实、编造数字、用 MBA 腔
- 这是把 LLM 的角色扮演能力当作**合成数据生成器**, 而不是当作真实用户。在真实产品里这个 Agent 会被替换成"接收 candidate UI 输入"。

### 4. Evidence Mapper
- **role: STANDARD** + temperature: 0.2 — 这一步最不该创造
- **skill: evidence-schema** — 包含字段语义、type 判定、insufficiency 触发规则
- **铁律**(写在 persona): 不发明 outcome、不发明数字、conversation_turn_ids 必须能回指
- 关键设计: starting_evidence_index 由 orchestrator 控制, 这样多批次抽取的 evidence_id 不会冲突。

### 5. Mechanism Modeler
- **role: HEAVY** — 唯一升档到 `deepseek-reasoner` 的 worker。命名是认知劳动最重的环节, 需要推理。
- **skill: mechanism-taxonomy** — 命名风格、四段结构、status 判定规则
- **temperature: 0.35** — 比抽取稍高, 因为命名需要一些创造
- 关键设计: persona 明确"默认不给 validated 状态" — 升级由 Skeptic 流程之后由 orchestrator 决定。这是把"自我评分"权力从 LLM 手里拿走。

### 6. Skeptic Reviewer
- **role: STANDARD** + temperature: 0.3
- **skill: skeptic-checklist** — 7 类偏差模式
- 关键设计: **不产新机制**, 只产 ReviewFindings (findings + repair_actions + confidence_delta)。这样它的输出形态固定, orchestrator 可以**确定性地**应用它。
- confidence_delta 范围 `[-0.5, +0.1]` — 不允许 Skeptic 大幅提分, 只能小幅认可或大幅降。

### 7. Report Composer
- **role: HEAVY** — 报告语言需要既准确又自然, 用 reasoner
- **skill: report-authoring** — 写作模板与风格规则
- **temperature: 0.4** — 自然语言需要一点变化, 但不能漂
- 关键设计: orchestrator 在收到 report 后**强制覆盖** summary 计数 和 validated/probable 列表, 防止模型把 hypothesis 的机制写进 validated 区。这是"结构化输出 + 业务规则后处理"的标准做法。

## 为什么没用 function calling / tool use

DeepSeek 的 Anthropic-Compatible API 暂未暴露 strict JSON schema 工具支持(从 smoke test 看), 因此我们走了"system prompt 强约束 + Pydantic 严格解析 + 失败重试"路线。

如果将来升级到 native function calling, 我们的 Agent 层基本不动 — 只要把 `LLMClient.complete_json` 内部实现切到 tool 即可。Schema 已经全是 Pydantic, 一行 `.model_json_schema()` 就能作为 tool input schema 注入。

## 为什么 confidence 由 Python 重算

`Pipeline._estimate_components()` 用 5 个明确维度(证据丰富度、跨情境复现度、内部一致性、候选人认可度、结果链接强度)算出一个**显式**置信度, 再与模型自己给的 confidence 各占 50% 混合。

理由(来自 arch.md):
> 把置信度拆解为五个子维度...置信度建议采用一套**明确声明为业务规则**的分数制, 而不要假装它是模型自然就有的"真概率"。

如果完全相信模型给的 confidence, 它会倾向给所有自己生成的东西打高分。

## 模型档位经济学

一次完整 6-turn 端到端运行的真实成本:
- ~18 LLM 调用
- ~20–25k 总 token
- ~90 秒 wall time
- 其中 HEAVY(reasoner) 用了 2 次(mechanism_modeler + report_composer), 占大头时间; 其余 16 次是 STANDARD(chat), 占大头次数

如果未来要把 worker 全部塞 HEAVY, 单次成本和时间都会 3-5×, 收益却不一定明显。**只在"需要推理才能做对"的位置升档**, 这是 arch.md 反复强调的原则。

# 实现过程中的真实坑与教训

## 坑 1: `deepseek-reasoner` 的 ThinkingBlock

第一次拿 `msg.content[0].text` 直接报 `AttributeError`。
**根因**: reasoning 模型返回 `[ThinkingBlock, TextBlock]`, 第一个 block 没有 `text` 字段。
**修复**: `extract_text_blocks(msg)` 遍历所有 block, 只拼接有 `text` 的那些, 丢掉 thinking。
**教训**: 任何"我以为 SDK 行为统一"的假设, 切换模型前都得验证一次。

## 坑 2: 模型偶尔会给 ```json``` 围栏

Prompt 写了"NO MARKDOWN FENCES", 模型 9 成时候听话, 但每 10 次有 1 次还是会带。
**修复**: `strip_json_fence()` 在客户端做双保险:
  1. 优先剥围栏
  2. 没围栏就找第一个 `{` 或 `[`, 走平衡括号扫描
  3. 失败再让 json.loads 报错触发重试
**教训**: LLM 的"听话率" ≠ 100%。客户端必须有兜底解析, 不能假设输入干净。

## 坑 3: `generated_at` 返回空字符串导致 Pydantic 报错

第一次端到端跑, Report Composer 把 datetime 字段填成 `""`, Pydantic 严格模式直接拒绝, 触发重试一次才成功。
**修复**:
1. `field_validator` 把 `""` / None 都 coerce 成 `now()`
2. Orchestrator 在拿到 report 后**主动覆盖** generated_at (双保险)
3. Prompt 加一句 "generated_at 不要填, 系统会设置"
**教训**: 给 LLM 的 schema 里, 凡是"系统应该自动填的字段", 必须在客户端做容错。不要假设模型会留空。

## 坑 4: Interviewer 老在一个事件里追问

3-turn 试运行, Interviewer 把 3 个 turn 全用在 hyp_04 上, 结果 Evidence Mapper 只能产 1 张 evidence, 直接挂掉 evidence_gate。
**根因**: Interviewer 自然倾向追深, 这个偏好正确, 但没人告诉它什么时候该切换。
**修复**: 在 orchestrator 那一层, **用 Python 数 history 里每个 hypothesis 的轮数**, 当某个 ≥ 2 就在 prompt 里注入 strategy_hint: "请切换"。
**教训**: "控制流"和"内容生成"应该解耦。LLM 负责"怎么问得好", Python 负责"该问哪个"。

## 坑 5: 模型自己给的 confidence 偏乐观

Mechanism Modeler 第一次跑, 给 mech_001 和 mech_002 都 0.85。但实际上证据强度差异很大。
**修复**: 不完全相信模型 confidence, 用 5 维 `ConfidenceComponents` 算一个**显式版**, 再做 50/50 blend。这样:
- 模型可以保留它的"语义判断"
- 系统拿回了"业务规则"的控制权
**教训**: "用模型给分" + "用规则给分" 各占 50, 比任何一种独跑都稳。这也是 arch.md "把置信度变成业务规则"的真实落地形态。

## 坑 6: Skeptic 输出格式飘

ReviewFindings 的 `confidence_delta` 范围我一开始没限制, 模型给出过 `-0.7` 这种数值, 导致后续打分崩。
**修复**: 在 Pydantic 用 `Field(ge=-0.5, le=0.1)` 锁死范围。+ 把 severity 写成 enum。
**教训**: Pydantic 是 LLM 的护栏, **能用 enum 别用 string, 能用 range 别用 float**。

## 坑 7: Report Composer 会"自作主张"把已降级的 mech 写进 validated 区

post-review 里 mech 是 hypothesis 状态, 但 Report Composer 在 validated_mechanisms 列表里仍然把它写出来了。
**根因**: 模型对 "status==hypothesis 的 mech 不要进 validated_mechanisms" 的指令理解不稳。
**修复**: Orchestrator 在拿到 report 后, **用 mechs_post 的 status 强制过滤** validated/probable 两个列表, 并重算 summary 的三个计数。
**教训**: 任何"模型理应自己算对"的计数 / 计算 / 过滤, 都应该在客户端再算一遍。不是不信任模型, 而是把责任放在确定性的代码里, 让 review/audit 更直接。

## 坑 8: Pydantic v2 的 `ConfigDict(extra="forbid")` 严格但**也**严格

我一开始用 `model_config = ConfigDict(extra="forbid")`, 结果模型偶尔多返回一个 `notes` 字段, 直接挂。
**修复**: 保留 `extra="forbid"` (好处大于坏处), 但 prompt 里**把完整 schema 列给模型**, 模型多数情况下就不会乱加字段了。少数情况下挂的, 走重试。
**教训**: 严格 schema 是好事, 但要给模型看清规矩。

## 坑 9: Skill body 在 prompt 里占字数

`SKILL.md` 写满后能到 1.5–3k token。如果每个 Agent 调用都把全部 body 注入, 单次提示 token 会膨胀很厉害。
**当前权衡**: 每个 Agent 只 load 自己需要的 1 个 Skill, 不 load 全部。
**未来方向**: 真正的 progressive disclosure 应该是 — Skill body 不直接进 system prompt, 而是放在一个工具调用里, 让 Agent 自己"按需读"。但 DeepSeek 的 Anthropic 接口目前不暴露 file tool, 所以这一步暂缓。

## 坑 10: simulated candidate 会"自我美化"

第一版 simulated_candidate 的 persona 写得不够严, 模型扮演候选人时会用 MBA 腔 ("我深刻理解到..."), 或者编造没有的数据。
**修复**: persona 明确禁止 "编造简历中没有的公司、产品、项目", "编造具体数字", "MBA 腔"; 允许"不太记得了 / 那不是我直接负责的"。
**教训**: 角色扮演的 Agent **比业务 Agent 更需要约束**, 因为 LLM 默认会"演得太好"。

## 通用原则

经过这一遭, 我把"LLM 应用工程"的核心心法压缩成 4 句话:

1. **Schema > Prompt > Model**: schema 锁住能锁的; prompt 引导剩下的; 模型档位最后再调。
2. **每条业务规则一个 deterministic 函数, 配一个 unit test**。不要把规则交给 LLM 重复推理。
3. **LLM 输出永远不可信**。客户端必须能解析、重试、覆盖。
4. **写代码之前先想:"这个步骤会不会让 LLM 撒谎得逞?"** 撒谎成立的可能性 = 系统对外说"validated"的概率。

这些不是"原则"是"伤疤换的"。

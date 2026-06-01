# 一次真实运行的全程解剖 (run_20260517_145205)

> 这一篇用最近一次成功 run, 把 7 个阶段、18 次 LLM 调用、4 张 evidence、2 个 mechanism、5 个 gate 全部走一遍, 让你看到系统在每一步做了什么。

## 输入
- `resume.redacted.md`: 一份脱敏的 macOS 终端安全架构师简历
- `target_role`: "macOS 终端安全架构师"
- `turns`: 6

## 阶段 1 — PII 扫描 (deterministic)

`scan_pii(resume_text)` 跑正则。这次返回 `[]` (因为简历已脱敏)。生成 `privacy_notes = ["未发现 PII"]`。

**为什么这一步不是 Agent**: 正则不需要 LLM。

## 阶段 2 — Intake (LLM call #1, STANDARD)

输入: 简历全文 + target_role
输出: `CandidateProfile`
- 5 个 core_experiences
- 4 个 hypotheses (其中 2 个 priority=high)
- 4 个 unknowns

hypothesis 示例:
- `hyp_01 [high]` 多层级安全事件建模与决策引擎设计
- `hyp_02 [high]` 从 0 到 1 构建安全产品的架构抽象与复用

**门控: sufficiency_gate**
- has high-priority hypothesis? ✓
- has core_experience? ✓
- **PASS**

## 阶段 3 — Interview (LLM calls #2–#13, 6×2)

每轮 = 一次 interviewer 调用 + 一次 simulated_candidate 调用。

第 t_01 轮:
> Q (target: hyp_04, cue: cues): "在 exp_01 中, 最早让你意识到需要设计多进程隔离架构 (LaunchDaemon+XPC) 来保证高可用的那个具体信号是什么?"
> A: "最早是有一次, 主服务因为网络过滤模块的内存泄漏直接崩溃了, 整个安全客户端都挂了…所以后来才拆成 LaunchDaemon 主服务加上独立的 XPC 子服务…"

注意: Interviewer 不接受抽象自评, 上来就抓"那个具体信号是什么"。Candidate 给出**两个具体 cues**: "主服务崩溃后整个客户端挂掉" + "复盘发现网络过滤模块代码路径复杂"。

第 t_02–t_03 继续追同一事件的 judgment 和 actions。

第 t_04 轮触发 **strategy_hint**:
> hyp_04 已经追了 2 轮足够深入. 下一轮请切到 hyp_01 或其他未覆盖的 hypothesis, 问一个新的具体事件 — 不再追当前事件.

interviewer 听话切到 hyp_03 (跨平台抽象), 问了 IOKit→ESF 的技术选型事件。

第 t_05–t_06 又切到 hyp_01 的 ev_004 (执行控制决策引擎签名误判事件)。

## 阶段 4 — Evidence Mapping (LLM call #14, STANDARD)

输入: 6 个 InterviewTurn
输出: `EvidenceBatch` 含 4 张 EvidenceCard

为什么是 4 张, 不是 6 张? 因为前 3 个 turn 是同一事件的不同切面(信号、判断、动作), Evidence Mapper 正确地把它们合并成 1 张 ev_001。

每张 evidence 都填了完整的 8 个字段(situation, goal, constraints, cues, judgment, actions, outcome, source_ref)。confidence 都在 0.75–0.85 之间。

**门控: evidence_gate** (min_incidents=3)
- 4 critical_incidents ≥ 3 ✓
- 每张都有 cues + judgment + actions + outcome ✓
- **PASS**

## 阶段 5 — Mechanism Modeling (LLM call #15, HEAVY)

输入: 4 张 EvidenceCard + 初始 hypotheses
输出: `MechanismBatch` 含 2 张 mechanism_card

模型把 4 张 evidence 聚成 2 组:
- mech_001 "跨情境对比定位根因" ← ev_001 + ev_003 (两个调试相关事件)
- mech_002 "基于长期兼容性选择技术路线" ← ev_002 + ev_004 (两个选型相关事件)

每个机制都有 cue_pattern / decision_rule / verification_style 三段结构 + boundary_conditions。

模型自己给 confidence = 0.85 和 0.80, status = probable。

**门控: naming_gate**
- 每个 mech 有 ≥2 distinct evidence_ids ✓
- 每个 mech 至少 1 张 critical_incident 支撑 ✓
- **PASS**

### 后处理: confidence 重算

Orchestrator 不直接相信模型给的 0.85。它用 `Pipeline._estimate_components()` 算了一个显式版本:
- evidence_richness ≈ 0.72 (2 张证据 + avg 0.83)
- cross_context_replication = 1.0 (2 张证据落在 2 个不同 experience_id)
- internal_consistency = 1.0 (没有 anti_evidence)
- candidate_endorsement = 1.0 (都是 critical_incident)
- outcome_link_strength = 1.0

加权和约 0.84, 与模型的 0.85 一致 → blended = 0.85。**status 暂时不变。**

## 阶段 6 — Skeptic Review (LLM calls #16–#17, STANDARD ×2)

对每个 mech 都调一次 Skeptic。Skeptic **真的找出问题**:

mech_001 findings:
- [HIGH] **overclaim**: "跨情境对比定位根因" 太宽泛, 几乎任何调试都能套
- [MEDIUM] simpler_alternative: 也许只是 google 错误码
- [MEDIUM] no_anti_evidence: 缺乏反例
- confidence_delta: **-0.25**

mech_002 findings:
- [HIGH] **causal_leap**: ev_004 (签名误判修复) 与"长期兼容性"无关
- [MEDIUM] simpler_alternative: ev_002 只是"避免用废弃 API"的常识
- [HIGH] **no_anti_evidence**
- confidence_delta: **-0.25**

### 后处理: orchestrator.apply_review() (deterministic)

按 arch.md §一致性门 的规则:
> 只要 Skeptic 找到未解决的强反例 (HIGH severity), 该机制就不能标记为 validated, 最多是 probable。

- mech_001: 0.85 - 0.25 = 0.60 + has_high → **probable** (conf 重命名为 0.61, 经过 confidence 重算细微调整)
- mech_002: 0.80 - 0.25 = 0.55 + has_high → conf < 0.6 → **hypothesis** (conf 0.597)

**门控: consistency_gate**
- 两个 high-severity finding 都有 repair_actions ✓
- **PASS**

## 阶段 7 — Report Composition (LLM call #18, HEAVY)

输入: 2 张 post-review mech + privacy_notes
输出: `ExtractionReport`

模型生成了:
- summary: {validated: 0, probable: 1, needs_more: 1}
- 1 个 probable_mechanism 含 resume_rewrite 和 interview_narrative
- 1 个 hypothesis 在 needs_more_evidence 计数里(不展开)

### 后处理: orchestrator 重写 summary

Orchestrator 不相信模型自己数对了, 用 `mechs_post` 的 status 重新计数, 并过滤报告里"幽灵"机制(模型可能把已降级的 mech 仍写进 validated 区)。

**门控: publish_gate**
- 所有 validated_mechanism 都有 evidence_ids ✓
- redacted_pii = True ✓
- **PASS**

## 最终产出

```
✓ 所有 5 个 gate 通过
报告: 0 validated / 1 probable / 1 hypothesis
1 个 probable mechanism 含完整 evidence_ids, 可直接用于简历改写
```

## 为什么 "0 validated" 不是失败

这是系统**诚实的表现**。Skeptic 找到了 high-severity 问题, orchestrator 据此降级。在 arch.md 的逻辑里:
> 高置信度结论必须 100% 有 evidence_ids; 报告中任何"高价值""稀缺""适配某岗位"的判断都必须可解释。

如果系统看到 2 个机制就批 2 个 validated, 那它就只是个 LLM-flatterer, 而不是萃取器。一个只有"probable"的报告比一个塞满"validated"的报告**对候选人更有价值**, 因为前者明确告诉他: "这两个机制证据已经不错, 但还需要一两次跨情境验证。"

## token 实际花销

| 阶段 | 调用数 | 大致 token |
|---|---|---|
| Intake | 1 | 2800 in / 1200 out |
| Interview (6×2) | 12 | ~9000 in / ~3000 out |
| Evidence Mapping | 1 | ~1500 in / ~1800 out |
| Mechanism Modeling | 1 (HEAVY) | ~1800 in / ~1200 out |
| Skeptic ×2 | 2 | ~1200 in / ~800 out |
| Report Composition | 1 (HEAVY) | ~700 in / ~900 out |
| **总计** | **18** | **16k in / 8k out** |

按 DeepSeek 当前价格, 一次完整跑的费用约 ¥0.05–0.10 量级。

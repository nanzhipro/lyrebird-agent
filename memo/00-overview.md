# Lyrebird 多 Agent 系统 — 实现备忘总览

本备忘录系列(00–N)记录从零到一构建 `arch.md` 中描述的「认知机制萃取多 Agent 系统」的完整过程。目的不是给出最终代码,而是把**每一步为什么这样做、有什么备选方案、踩过哪些坑**留下来,让后来者能复用。

## 任务核心

把候选人的简历与对话,通过六个专职 Agent 协作:
1. **Intake** — 从简历生成初步假设
2. **Interviewer** — 围绕关键事件做深度追问
3. **Evidence Mapper** — 把叙述压成结构化证据卡
4. **Mechanism Modeler** — 从证据卡命名认知机制
5. **Skeptic** — 反驳与查漏
6. **Report Composer** — 写成可用报告

并由 Orchestrator 协调 + 一组 deterministic validator 把关。

## 关键约束(来自 arch.md)

| 约束 | 影响 |
|---|---|
| 多 Agent 只用于真正需要并行/隔离的环节 | PII 检测、schema 校验、置信度计算 = 确定性脚本,不是自由 Agent |
| 证据先于命名 | mechanism_card 必须能回溯到 evidence_card,evidence_card 必须能回溯到来源 |
| Skill 是程序性知识层 | Skills 目录放可复用的提示模板/词表,候选人私有数据走 artifact store |
| 上下文是稀缺资源 | 跨 Agent 不靠"传话",靠 artifact handoff |
| 保留人类透明度 | 每个命名都要说明依据,候选人可随时干预 |

## 技术选型决策

### 1. 语言:Python 3.11+

理由:
- `anthropic` 官方 SDK 一等公民
- Pydantic v2 提供 schema-first 的结构化输出能力
- 与 LLM/AI 生态最契合

备选:TypeScript。放弃原因:Pydantic 比 zod 更适合做 schema-driven LLM 输出,而且这个项目不是 web 服务。

### 2. LLM 接入:DeepSeek 的 Anthropic-Compatible API

base_url:`https://api.deepseek.com/anthropic`

这意味着:
- 用 `anthropic.Anthropic(base_url=..., api_key=...)` 可以无缝调用
- 模型名直接用 DeepSeek 提供的:`deepseek-chat`、`deepseek-reasoner`
- arch.md 里写的 "Opus / Sonnet / Haiku" 三档,我们映射到 DeepSeek 的两档:
  - **deepseek-reasoner**(推理/慢/贵)→ 替代 Opus 用于 Orchestrator 综合、Mechanism Modeler 关键命名
  - **deepseek-chat**(快/便宜)→ 替代 Sonnet/Haiku 用于其他角色

### 3. 数据契约:Pydantic v2

四个核心 schema:`CandidateProfile`、`EvidenceCard`、`MechanismCard`、`ExtractionReport`。

为什么不用 JSON Schema 原生?Pydantic 既能生成 JSON Schema 喂给 LLM,又能在 Python 端做 strict 校验,一套两用。

### 4. Artifact Store:本地 JSON 文件

理由:
- arch.md 强调 artifact 应该可持久化、可审计
- MVP 阶段不需要数据库
- 每条 artifact 一个文件,带 `artifact_id` 和 `provenance` 字段
- 后续可平滑迁移到 SQLite / 对象存储

### 5. TDD

先写测试,再写实现。验证 pytest 跑得通,再写 prod 代码。

### 6. 目录结构

```
lyrebird-agent/
├── src/lyrebird/
│   ├── schemas.py           # Pydantic models
│   ├── llm/                 # DeepSeek client wrapper
│   ├── validators/          # PII guard, schema validator, citation checker, confidence scorer
│   ├── agents/              # 6 worker agents + orchestrator
│   ├── artifact_store.py    # JSON artifact store
│   ├── skills.py            # Skills loader
│   └── pipeline.py          # End-to-end runner
├── tests/                   # pytest TDD
├── skills/                  # SKILL.md modules
├── memo/                    # 实现备忘
├── artifacts/               # 运行时产物
├── runs/                    # 完整 run 的 transcript
└── pyproject.toml
```

## 开发节奏

1. 骨架 + 依赖 → 跑通 `pytest`
2. Schemas + 单测
3. LLM Client(mock 测试 + 真实 smoke test)
4. Validators + 单测
5. Artifact Store + 单测
6. Skills 库(纯 Markdown,不需要测试)
7. 单个 Agent(从最简单的 Intake 开始)+ 真实调用 smoke
8. 其余 5 个 Agents
9. Orchestrator 串起来
10. 用 `resume.redacted.md` 跑端到端

每一步通过才进下一步。

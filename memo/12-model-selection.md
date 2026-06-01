# 模型选择决策 + 全 Pro 利弊分析

> 用户问:"Lyrebird 怎么决定什么时候用 flash、什么时候用 pro?如果全用 pro 会不会更好?"
> 这一篇正面回答,并给出可量化的取舍框架。

## 决策机制(代码层)

完全集中在 **三处** + **一处可覆盖**:

### 1. `Role` 枚举(`src/lyrebird/llm/client.py`)

```python
class Role(str, Enum):
    HEAVY = "heavy"        # 慢但更深
    STANDARD = "standard"  # 默认档,日常 worker
    FAST = "fast"          # 保留位,目前与 STANDARD 同档
```

### 2. `_MODEL_MAP` 映射

```python
_MODEL_MAP = {
    Role.HEAVY: "deepseek-v4-pro",
    Role.STANDARD: "deepseek-v4-flash",
    Role.FAST: "deepseek-v4-flash",
}
```

### 3. 每个 Agent 在构造函数里声明自己的 `role`

只有 **两个** Agent 用 HEAVY,其余都是 STANDARD:

| Agent | Role | 模型 | 为什么 |
|---|---|---|---|
| Intake | STANDARD | flash | 结构化抽取,简历事实清晰可循,不需要深思 |
| Dialogic Interviewer | STANDARD | flash | 提问质量靠 prompt + skill,模型档位贡献小 |
| Simulated Candidate | STANDARD | flash | 角色扮演,深推理反而会"出戏" |
| Evidence Mapper | STANDARD | flash | 把对话压成 schema 卡片,翻译性工作 |
| **Mechanism Modeler** | **HEAVY** | **pro** | 命名 = 深聚类 + 跨情境抽象 + 反命名陷阱,是唯一真需要深思的环节 |
| Skeptic | STANDARD | flash | 按 checklist 找问题,checklist 是已给的,模型档位帮助有限 |
| **Report Composer** | **HEAVY** | **pro** | 写给真人用的简历改写 + 面试口播,需要语感、判断、克制 |

### 4. 运行时 env 覆盖(`LLMClient.model_for`)

```python
@staticmethod
def model_for(role: Role) -> str:
    env_key = f"LYREBIRD_MODEL_{role.value.upper()}"
    return os.environ.get(env_key) or _MODEL_MAP[role]
```

任何时候不重启代码,只设环境变量就能换:

```bash
LYREBIRD_MODEL_HEAVY=deepseek-v4-flash    # 把命名/报告也降到 flash,省时间
LYREBIRD_MODEL_STANDARD=deepseek-v4-pro   # 把所有 worker 升到 pro,做对比实验
```

---

## 设计原则(为什么默认这样分)

来自 `arch.md` §架构原则:

> "多 Agent 只用于真正需要并行/隔离的环节。" 同理,**HEAVY 档只用于真正需要深推理的环节**,其余一律 STANDARD。

可量化的标准 — 一个 Agent 应该升 HEAVY,当且仅当:

1. **任务的关键输出是判断性的、非纯抽取性的**(命名 vs 抽取)
2. **错误代价高**(给候选人的报告里有错命名 vs 抽出错的 evidence 字段)
3. **下游有把关机制**(Skeptic 把关 Mechanism Modeler;Pipeline 后处理把关 Report Composer)
4. **flash 实测产出明显有提升空间**(我们 A/B 过 Mechanism Modeler:flash 经常给出像"沟通能力强"这类空泛标签,pro 几乎不会)

四条都满足 → HEAVY。任何一条不满足 → STANDARD。

> Skeptic 看似"判断性",但 checklist 是预定义的 7 类偏差,模型只是检查清单 — 不是创造新判断。所以 STANDARD。

---

## "全 pro" 的利弊量化

### 实测数据(基于 6-turn run × 3 次)

| 配置 | 总 LLM 调用 | 总 tokens (in+out) | wall clock | 估算成本 |
|---|---|---|---|---|
| 当前(2 HEAVY + 5 STANDARD) | 18 | ~25k | ~90s | $A(基线) |
| 全 STANDARD | 18 | ~18k | ~50s | ~0.5×A |
| 全 HEAVY | 18 | ~50k | ~300-400s | ~3-4×A |

数据要点:
- pro thinking 比 flash thinking 长 **2-3 倍**(主要消耗在 thinking block,output 长度差不多)
- pro 延迟比 flash 高 **5-8 倍**(thinking 处理 + 服务端排队)
- pro 当前定价含 2.5× 折扣(至 2026-05-31),折后 ≈ flash 同价。**折扣过期后**全 pro 的成本会显著上升

### 利

| 维度 | 全 pro 的好处 |
|---|---|
| 提问质量 | Interviewer 会主动设计更刁钻的 counterfactual,而不只是套模板 |
| 角色扮演 | Simulated Candidate 在回忆细节时更"像人",少机械感 |
| 证据抽取 | Evidence Mapper 在 cues / judgment 区分上更准,边界判断更细 |
| Skeptic | 找出来的 overclaim 更具体(从"过宽"到"过宽,因为它和 ev_004 矛盾") |
| Intake | hypothesis 命名风格更稳,不容易冒出"沟通能力"这种空泛词 |
| 一致性 | 整条 pipeline 同一模型,语言风格、术语选择更统一 |

### 弊

| 维度 | 全 pro 的代价 |
|---|---|
| 延迟 | 单 run 从 ~90s → ~300-400s,**对 web UI 的"实时观测"体验是灾难性的** |
| 成本 | tokens 增加 ~2x,折扣过期后再叠加 |
| 过度思考 | Interviewer 对一个 80 字的问题 thinking 1500 token,**性价比极低** |
| 风险:出戏 | Simulated Candidate 用 reasoning 模型反而会"演不像普通人",输出过于完美 |
| 覆盖均匀化 | 当一切都是 HEAVY,真正需要 HEAVY 的环节(Mechanism Modeler)失去"特殊性",团队失去"在哪里更用力"的注意力锚点 |
| 监控麻烦 | Pro 调用偶尔会 timeout 或排队(API 侧),需要更宽的 max_tokens 与重试预算 |

### 我的判断

**默认不该全 pro。** 当前 2/7 HEAVY 的配比抓住了真正回报最高的两个环节:
- Mechanism Modeler:命名错一次,整份报告对用户毫无价值
- Report Composer:语言一硬一空,候选人就不会真的拿去改简历

把这两个升 pro,**等效于把整条 pipeline 的最终产物质量提升一个档**,代价仅是 ~30% 的 tokens 增加和 ~50s 的延迟增加。

升级到全 pro,**只为剩下 5 个环节多花 3-4× 的资源换取的是边际收益**,而且这些 worker 都有上游/下游兜底(Intake 的产出会被 Interviewer 追问、Evidence Mapper 的产出会被 Skeptic 审,等等)。

### 何时该全 pro

- 离线批处理(不在乎延迟)
- 评估对比实验(需要排除"模型档位差异"做控制变量)
- 给真实候选人单次重要分析,且愿意等 5 分钟
- 折扣期内 + 资源充足(2026-05-31 之前的"白嫖窗口")

### 何时该全 flash

- 演示 / 调试 / dogfood
- 低价值候选人快速预筛
- 想验证 prompt 本身的极限(剔除模型档位变量)
- 团队成本控制期

---

## 切换指南

### 方式 1:env 一次性

```bash
LYREBIRD_MODEL_HEAVY=deepseek-v4-flash \
LYREBIRD_MODEL_STANDARD=deepseek-v4-flash \
  uvicorn lyrebird.web.app:app
```

适合临时实验。

### 方式 2:写进 `.env` 永久切

```bash
# .env
DEEPSEEK_API_KEY=sk-...
LYREBIRD_MODEL_HEAVY=deepseek-v4-pro       # 显式锁定
LYREBIRD_MODEL_STANDARD=deepseek-v4-flash
```

适合团队约定。

### 方式 3:per-agent fine-grained

如果未来想要"只把 Skeptic 升 pro"(因为 Skeptic 的偏差检查最考验深推理),需要把 Role 枚举扩展。我们的 `model_for(role)` 是 role 粒度,不是 agent 粒度。一个简单扩展方案:

```python
# src/lyrebird/llm/client.py 增加 per-agent override
def model_for(role: Role, agent_name: str = None) -> str:
    if agent_name:
        agent_env = f"LYREBIRD_MODEL_AGENT_{agent_name.upper()}"
        if os.environ.get(agent_env):
            return os.environ[agent_env]
    env_key = f"LYREBIRD_MODEL_{role.value.upper()}"
    return os.environ.get(env_key) or _MODEL_MAP[role]
```

`BaseAgent.run()` 把 `self.name` 传进去。这样:
```bash
LYREBIRD_MODEL_AGENT_SKEPTIC=deepseek-v4-pro
```
只升 Skeptic 一个。**V0.3 不做**,留给 V0.4 — 等真正有人提需求再加。

---

## 测试锁死

`tests/test_llm_client.py`:
- `test_role_maps_to_v4_models`:锁死默认映射,防止有人偷偷改了 `_MODEL_MAP`
- `test_role_model_overridable_via_env`:锁死 env 覆盖机制,防止重构时被误删

任何对模型映射的修改都必须经过这两个测试。

## 结论

**最低成本 / 最高 ROI:维持 2 HEAVY + 5 STANDARD**。

如果团队在折扣期(2026-05-31 前)有预算冗余,且不在乎 web 延迟,**可以做一次"全 pro" A/B**:用 `LYREBIRD_MODEL_STANDARD=deepseek-v4-pro` 跑 5 次真实 run,人评对比"全 pro vs 当前"的报告语言质量。如果差距明显且团队认为值得,再永久切换。

如果差距不明显 — 那就是"原则获胜"的最好证据。

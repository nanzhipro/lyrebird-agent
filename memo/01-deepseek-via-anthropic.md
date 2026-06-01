# DeepSeek 的 Anthropic-Compatible API 接入要点

## 接入方式

```python
from anthropic import Anthropic
client = Anthropic(
    base_url="https://api.deepseek.com/anthropic",
    api_key=os.environ["DEEPSEEK_API_KEY"],
)
```

只要 base_url 指向 DeepSeek,SDK 的 `messages.create()` 行为与官方 Anthropic 一致(messages、system、stop_reason、usage 都可用)。

## 模型映射(arch.md 三档 → DeepSeek 两档)

| arch.md 角色档位 | DeepSeek 模型 | 说明 |
|---|---|---|
| Opus(Orchestrator 综合、Mechanism Modeler) | `deepseek-reasoner` | 慢、贵、强推理。返回内容里**第一个 block 是 ThinkingBlock**,第二个才是 TextBlock |
| Sonnet(大多数 worker) | `deepseek-chat` | 快、便宜、稳。直接返回 TextBlock |
| Haiku(高频结构化抽取) | `deepseek-chat` | 同上,DeepSeek 不区分轻量与中量 |

## 关键坑:`deepseek-reasoner` 的 content 结构

```python
msg = client.messages.create(model="deepseek-reasoner", ...)
# msg.content = [ThinkingBlock(...), TextBlock(...)]
# 不能直接 msg.content[0].text — 会 AttributeError
```

正确写法:

```python
text = next(b.text for b in msg.content if hasattr(b, "text"))
```

## JSON 结构化输出策略

DeepSeek 的 Anthropic 接口暂不暴露 strict JSON schema 工具(从 smoke test 看),但**只要 system prompt 写明"只回 JSON,无前后缀,无 markdown 围栏"**,实测 `deepseek-chat` 几乎 100% 听话。

我们的策略是:
1. **system prompt 强约束**:"只输出 JSON,符合下面这个 schema:..."
2. **Pydantic 强校验**:返回后立刻用 Pydantic 反序列化,失败则强制重试
3. **失败保护**:重试 N 次仍失败,降级到更小 schema 或返回明确错误

## 重要发现

- `deepseek-chat` 输出 JSON 偶尔会在前面加 ```json ... ``` 围栏,即便要求别这样。在客户端做"剥围栏"是必要的。
- token 计数与 Anthropic 兼容,但 cache_creation/cache_read 字段在 DeepSeek 端目前总是 0(没有 prompt caching)。
- `stop_reason` = `end_turn` 正常完成;`max_tokens` 表示截断。

## 后续策略

- LLM Client 封装一个 `complete_json(model, system, user, schema)` 方法,内部:
  1. 调 messages.create
  2. 提取 TextBlock 的 text
  3. 剥除 markdown 围栏
  4. Pydantic 解析
  5. 失败重试(指数退避,最多 3 次)
- 记录每次调用的 usage(用 token 数评估成本)

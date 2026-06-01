# V4 模型升级 + i18n 架构

> 这一篇覆盖 V0.3 的两个独立改动:DeepSeek V4 模型迁移(含 thinking-block 适配)、UI 国际化(中英双语,可扩展)。背景:用户在生产日志里发现 `complete_json attempt 1/3 failed: Unterminated string starting at line 16 column 31`,这是 V4 thinking-block 吃 token 引起的截断。

## Part 1 — DeepSeek V4 迁移

### 背景与官方变化

按 [DeepSeek 官方定价文档](https://api-docs.deepseek.com/zh-cn/quick_start/pricing) (2026 Q1):

| 旧 ID(将弃用) | 新 ID | 用途 |
|---|---|---|
| `deepseek-chat` | `deepseek-v4-flash` | 通用对话 / 快 / 便宜 |
| `deepseek-reasoner` | `deepseek-v4-pro` | 重推理 / 强 |

V4 默认开启 **thinking mode**(包括 Flash)。即:每次 `messages.create` 返回的 `content` 数组是 `[ThinkingBlock, TextBlock]`,**ThinkingBlock 计入 max_tokens 预算**。

### 我们的 Role → 模型映射

```python
_MODEL_MAP = {
    Role.HEAVY: "deepseek-v4-pro",      # Orchestrator 综合 / Mechanism Modeler / Report Composer
    Role.STANDARD: "deepseek-v4-flash", # 大多数 worker
    Role.FAST: "deepseek-v4-flash",     # (FAST 与 STANDARD 同档,留作未来扩展)
}
```

且支持运行时 env 覆盖:
```bash
LYREBIRD_MODEL_HEAVY=deepseek-v4-flash  # 想省钱测试时降档
```

### Bug 修复:"Unterminated string" 截断

#### 根因链
1. V4 默认 thinking,thinking block 长 200~1500 token,**算进 max_tokens**
2. V0.1 时 mechanism_modeler 给 `max_tokens=4000` 是按 V3 不带 thinking 设计的
3. V4 切换后,thinking 吃掉 ~1500 token 预算后,JSON 输出空间不足
4. 模型在 JSON 字符串中间被截断 → `{"name": "约束建模后再` ← 没闭合 `"`
5. `json.loads()` 抛 `Unterminated string starting at: line 16 column 31`
6. retry 用同样的 max_tokens 再问一次 → 同样截断

#### 修复点 1:检测 `stop_reason == "max_tokens"` 直接 bump

```python
stop_reason = getattr(msg, "stop_reason", None)
if stop_reason == "max_tokens":
    raise _Truncated(f"hit max_tokens={current_max_tokens}")
# ...
except _Truncated:
    bumped = min(int(current_max_tokens * 1.6), self.MAX_TOKENS_CAP)
    current_max_tokens = bumped
```

#### 修复点 2:解析错误也可能是截断(stop_reason 未必准)

```python
except json.JSONDecodeError as e:
    looks_truncated = "Unterminated" in str(e) or "Expecting" in str(e)
    if looks_truncated and current_max_tokens < self.MAX_TOKENS_CAP:
        current_max_tokens = min(int(current_max_tokens * 1.6), 16000)
```

#### 修复点 3:基线 max_tokens 上调

| Agent | V0.1 max_tokens | V0.3 max_tokens | 理由 |
|---|---|---|---|
| intake | 3000 | 5000 | 简历较长 + thinking |
| interviewer | 600 | 1500 | 短问题但 thinking 占大头 |
| simulated_candidate | 600 | 1500 | 短答案 + thinking |
| evidence_mapper | 4000 | 6000 | N 张证据卡 + thinking |
| mechanism_modeler | 4000 | 8000 | **Pro thinking 2-3k** |
| skeptic | 2000 | 3000 | findings 列表 |
| report_composer | 4000 | 6000 | Pro thinking + 报告体 |

注意:增加 max_tokens **不会增加成本**(只计实际生成的 output tokens),只是给模型更大的"绳子"。

### 教训

1. **任何带 thinking 的模型都不能直接复用旧 max_tokens 配置**。Anthropic Sonnet 3.7、DeepSeek V4 都是这样。
2. **检测+自动 bump 比"教模型节省"更可靠**。给模型加"请回复简短"只能缓解,真的不够时还是会截断。
3. **stop_reason 不是唯一的信号**。模型偶尔会以 `end_turn` 结束但输出仍是不完整 JSON(原因不明,可能是 SDK 翻译)。所以 `"Unterminated" in str(e)` 兜底必须存在。

### 测试锁死

`tests/test_llm_client.py::test_complete_json_bumps_max_tokens_on_truncation`:
- 第一次返回 `stop_reason="max_tokens"`
- 第二次返回完整 JSON
- 验证客户端**第二次调用的 max_tokens 严格大于第一次**

这条测试就是这次 bug 的回归屏障。任何未来把 truncation handling 改回"原样重试"的修改都会让它红。

---

## Part 2 — i18n 架构

### 目标

1. 默认中文
2. 支持英文
3. 加新语言成本接近零(一个 JSON 文件)
4. 加新字符串覆盖检查自动化(防双语漂移)
5. 用户切换语言能持久化

### 三层协商(标准 web 模式)

按优先级:

```
?lang=en  query param        — 最高,适合分享 URL
↓
Cookie: lyrebird_lang=en      — 用户上次选择
↓  
Accept-Language: zh-CN,en;q=0.8  — 浏览器默认
↓
default = "zh"                 — 兜底
```

实现在 `src/lyrebird/i18n/loader.py::negotiate_locale`,统一函数,API 路由和首页都走它。

### 文件布局

```
src/lyrebird/i18n/
├── __init__.py        # public: I18nRegistry, negotiate_locale
├── loader.py
└── locales/
    ├── zh.json        # default 中文
    └── en.json
```

### 三层 fallback(locale 内部)

加载时为每个 locale 构造一份 `dict[flat_key, value]`。查询 `t(locale, key)`:

```
locale 的 key 表 → 找到? → 返回
↓ 没找到
default locale 的 key 表 → 找到? → 返回
↓ 没找到
literal key 字符串 → 返回(暴露 bug)
```

第二层 fallback 的好处:**新加 zh 字符串时,即使没立刻翻译到 en,英文用户也能看到中文文案,而不是看到 "form.target_role.label" 这样的原始 key**。

### 双语 key 覆盖检查(自动化)

`tests/test_i18n.py::test_project_locales_have_matching_keys`:
- 加载 zh.json 与 en.json
- 计算两边 flat key set
- 断言对称差为空

加新字符串的标准流程:
1. 在 zh.json 加 `"foo.bar": "中文文案"`
2. 在 en.json 加 `"foo.bar": "english text"`
3. `pytest tests/test_i18n.py` 通过

只改一边 → CI 红。这把"忘了翻译"从可能的运行时 bug 变成 CI 时的失败。

### JSON shape: 嵌套写,扁平用

人写 zh.json 时用嵌套(可读):
```json
{
  "form": {
    "target_role": {
      "label": "目标岗位",
      "placeholder": "例如..."
    }
  }
}
```

加载时 flatten 为 `"form.target_role.label" → "目标岗位"`,O(1) 查询。变量插值用 `{name}` 占位:
```json
{"errors.network": "网络错误:{message}"}
```

### Frontend 集成方案

#### HTML 端:opt-in 属性
```html
<button data-i18n="form.start">Start</button>          <!-- textContent -->
<input data-i18n-placeholder="form.resume.placeholder"/>  <!-- placeholder -->
<p data-i18n-html="hero.small_html"></p>                  <!-- innerHTML, for links -->
```

`applyI18nToDom()` 遍历所有三种属性,赋值。

#### JS 端:`t(key, vars)` 函数

任何 JS 动态生成的字符串走 `t()`:
```js
els.runStatus.textContent = t("obs.status.running");
alert(t("errors.network", { message: e.message }));
```

#### 切换语言不刷新页面

```js
async function switchLocale(locale) {
  await loadLocale(locale);       // 拉新字符串
  renderStageStrip();              // JS 动态生成的部分重渲染
  refreshDynamicStrings();         // 当前状态文案更新(running / starting / 等)
  await buildLanguageSwitcher();   // active 标记更新
}
```

`refreshDynamicStrings()` 是关键 — 任何 JS 把 textContent 设过的元素,都要在 dataset 里记下 i18n key(`data-status-key="obs.status.running"`),切换时按 key 重译。

### 后端 API

```
GET /api/i18n/locales        →  {default, current, locales: [{code, name, native, html_lang}, ...]}
GET /api/i18n/{locale}       →  {locale, strings: {flat_key: value, ...}}
GET /                         →  设 Set-Cookie: lyrebird_lang=<negotiated>
```

`/api/i18n/{locale}` 还会 Set-Cookie(持久化用户的显式选择)。

`html_lang` 字段重要:`zh-Hans` 而不是 `zh`(W3C 推荐),帮助辅助技术正确朗读。

### 为什么客户端渲染,不是服务端模板

候选方案:
- 服务端 Jinja 模板,根据 locale 渲染 → **放弃**。需要构建/缓存 + 切换语言要刷整页。
- 客户端拉 JSON,JS 替换 → **采用**。零构建,切换语言不刷整页。

代价:首屏会有 ~100ms 的 "未翻译闪烁"(HTML 的默认文本被 JS 替换)。我们让 HTML 默认就放 zh(因为这是 default locale),所以中文用户**不会看到闪烁**,英文用户会看到 100ms 中文 → 英文。如果需要消除,可以在 HTML 模板里直接渲染对应 locale,但 V0.3 不需要。

### Agent prompts 不在 i18n 范围

这次只做 UI i18n。Agent 的 persona(中文)、SKILL.md(中文)、generated content(LLM 跟随 input 语言)都不动。

英文 resume 给 LLM,它会**自然**用英文产出 evidence_card 字段、mechanism_card.name 等 — 这部分不需要 i18n,LLM 自带能力。

如果将来需要"英文 UI + 强制 prompt 也英文",方案是:
1. 给每个 agent 加 `persona_locale: dict[str, str]` map
2. 在 PERSONA 选 locale 时按 ctx.locale 取
3. 同样的 key parity test 锁死

V0.3 不做。

### 扩展指南:加新语言(法语为例)

1. **复制** `src/lyrebird/i18n/locales/zh.json` 为 `fr.json`,翻译每个 value
2. **改 meta**:`"lang_native": "Français"`,`"html_lang": "fr"`
3. **跑测试** `pytest tests/test_i18n.py::test_project_locales_have_matching_keys` — 必须过
4. **重启 server**,fr 自动出现在 `/api/i18n/locales` 和语言切换器

零代码改动。

### 扩展指南:加新字符串

1. 在所有 `locales/*.json` 加同一个 key
2. 在 HTML 加 `data-i18n="..."` 或在 JS 用 `t("...")`
3. CI 跑 `test_project_locales_have_matching_keys`

如果只想先快速 ship 中文,后翻 en:fallback 链会让英文用户**看到中文文案**而不是看到 key,所以**不会阻塞发布**。但 CI 仍然会红 —这是设计要求,提醒"还有翻译债"。

---

## 验证

执行 `pytest`:
- **129 passed, 1 skipped** (V0.3 共增加 30 个测试)
- 11 个 EventBus + 13 web API + 17 i18n loader + 10 i18n web API + 2 新增 LLM client

通过 `gstack browse` 截图存档:
- `docs/screenshots/lyrebird-zh.png` — 中文界面全图
- `docs/screenshots/lyrebird-en.png` — 英文界面全图

真实 v4 run 验证(待 monitor 反馈)— 主要看是否还有 `complete_json failed: Unterminated string` 报错。如果有,truncation auto-bump 机制就会接住。

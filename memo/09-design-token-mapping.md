# Design.md → CSS token 落地映射

> 把 `Design.md` 描述的 Anthropic / Claude.ai 设计系统翻译到 `styles.css` 的过程。这一篇是给后来改 UI 的人看的: "我想换个颜色 / 字体 / 间距, 应该改哪里?"

## 设计哲学(必须先内化, 不然改出 off-brand)

`Design.md` 的核心三件事:

1. **暖奶油底色 (cream canvas)** — 不是冷灰白。`#faf9f5` 是品牌差异化的起点。任何"我觉得加点蓝看起来更专业"的冲动都要压住。
2. **珊瑚色克制**(coral primary) — 只在 primary CTA 和 full-bleed 召唤卡片用。不要"为了好看"撒点珊瑚到处都是。
3. **三明治节奏** — 段落之间 cream → cream-card → dark-mockup → cream → coral-callout → dark-footer 交替, 不允许相邻两段同表面色。

我们的页面有 5 个 band, 节奏严格遵守:

```
hero (cream canvas)
  ↓ cream-card 嵌入 (form)
observability (cream canvas)
  ↓ dark-navy 嵌入 (pipeline timeline + event log)
  ↓ cream-card 嵌入 (agent feed)
report (cream canvas)
  ↓ cream-card 嵌入
about (surface-soft, 比 canvas 稍暗)
footer (surface-dark)
```

## Token → CSS 变量 一一对应

| Design.md token | CSS 变量 | Hex | 用在哪 |
|---|---|---|---|
| `{colors.canvas}` | `--canvas` | `#faf9f5` | `body` 底色, 输入框背景, 单独 stat 卡 |
| `{colors.surface-soft}` | `--surface-soft` | `#f5f0e8` | About 段背景 |
| `{colors.surface-card}` | `--surface-card` | `#efe9de` | 所有 `.feature-card` (form, agent feed, report) |
| `{colors.surface-cream-strong}` | `--surface-cream-strong` | `#e8e0d2` | model badge 背景 |
| `{colors.surface-dark}` | `--surface-dark` | `#181715` | Pipeline timeline 卡, event log 卡, footer |
| `{colors.surface-dark-elevated}` | `--surface-dark-elevated` | `#252320` | Pending 状态的 stage chip |
| `{colors.surface-dark-soft}` | `--surface-dark-soft` | `#1f1e1b` | Running 状态 chip 内底色, event log 内底色 |
| `{colors.hairline}` | `--hairline` | `#e6dfd8` | 1px 边框: 输入框、stat 卡、agent row |
| `{colors.hairline-soft}` | `--hairline-soft` | `#ebe6df` | 顶部 nav 下边线 |
| `{colors.ink}` | `--ink` | `#141413` | 所有 display 标题, 输入框文字 |
| `{colors.body-strong}` | `--body-strong` | `#252523` | Lead 段, label-text |
| `{colors.body}` | `--body` | `#3d3d3a` | 默认正文 |
| `{colors.muted}` | `--muted` | `#6c6a64` | 次级标签 |
| `{colors.muted-soft}` | `--muted-soft` | `#8e8b82` | 占位说明 |
| `{colors.on-primary}` | `--on-primary` | `#ffffff` | Coral 按钮文字 |
| `{colors.on-dark}` | `--on-dark` | `#faf9f5` | 深色面上的文字 |
| `{colors.on-dark-soft}` | `--on-dark-soft` | `#a09d96` | 深色面上的次级文字 |
| `{colors.primary}` | `--primary` | `#cc785c` | "Start extraction" 按钮, focus ring, run 中的 stage chip 描边 |
| `{colors.primary-active}` | `--primary-active` | `#a9583e` | Hover 时变暗 |
| `{colors.accent-amber}` | `--accent-amber` | `#e8a55a` | "running" 状态 badge, event log 中 `started` 类型颜色 |
| `{colors.accent-teal}` | `--accent-teal` | `#5db8a6` | (备用, 当前未用) |
| `{colors.success}` | `--success` | `#5db872` | "completed" badge, 已完成 stage chip ✓, validated mechanism |
| `{colors.error}` | `--error` | `#c64545` | "failed" badge, 失败 stage chip ✕ |

## Typography → CSS 变量

| Design.md face | CSS 变量 | Web font | 用在哪 |
|---|---|---|---|
| Copernicus / Tiempos Headline | `--font-display` | **Cormorant Garamond** (Google Fonts) | 所有 `.display-*` 标题, 报告 stat 数字, mechanism 名字 |
| StyreneB | `--font-body` | **Inter** | `body`, 按钮, 输入框, 标签 |
| JetBrains Mono | `--font-mono` | **JetBrains Mono** (开源原版) | run_id, token 数, event log, evidence pill |

为什么 Cormorant Garamond:
- Design.md 在 "Known Gaps" 章节明确指 Copernicus 是 Anthropic 私有授权
- 三个推荐替代是 **Cormorant Garamond / EB Garamond / Tiempos Headline**
- Cormorant 是最接近 Copernicus 的"轻盈、负字距、文学感"的开源衬线
- weight 500 + `-0.3px ~ -1.5px` 字距 = 编辑体感

display headline 三个绝对不允许的做法:
1. **bold (700)** — 看起来"很重很爆款", off-brand
2. **正常字距** — 没有负字距, 衬线字会"撑开", off-brand
3. **换成 sans-serif** — 立刻变成"另一个 AI 工具"

## Spacing → CSS 变量

| Design.md token | CSS 变量 | 值 | 用在 |
|---|---|---|---|
| `{spacing.xxs}` | `--space-xxs` | 4px | (微调) |
| `{spacing.xs}` | `--space-xs` | 8px | label-text 与 input 间隙 |
| `{spacing.sm}` | `--space-sm` | 12px | stage chip 之间 |
| `{spacing.md}` | `--space-md` | 16px | field-row 列间隙 |
| `{spacing.lg}` | `--space-lg` | 24px | container 左右 padding, 大卡内子区块 |
| `{spacing.xl}` | `--space-xl` | 32px | **feature-card 内边距** (Design.md 规定) |
| `{spacing.xxl}` | `--space-xxl` | 48px | (大段落间) |
| `{spacing.section}` | `--space-section` | 96px | **band 与 band 之间** (Design.md 规定) |

## Border Radius → CSS 变量

| Design.md token | CSS 变量 | 值 | 用在 |
|---|---|---|---|
| `{rounded.xs}` | `--r-xs` | 4px | (微) |
| `{rounded.sm}` | `--r-sm` | 6px | mechanism status badge, token totals 小 chip |
| `{rounded.md}` | `--r-md` | 8px | **按钮**, **输入框**, **stage chip**, agent row |
| `{rounded.lg}` | `--r-lg` | 12px | **feature card**, dark mockup card |
| `{rounded.xl}` | `--r-xl` | 16px | (hero illustration 用, 我们没用) |
| `{rounded.pill}` | `--r-pill` | 9999px | status badge (`.badge-pill`), evidence pill |

层级是 Design.md 明确规定的"button=8, card=12, hero=16"。改任何一个都要确保不打破阶梯关系。

## 改 UI 的三条原则

### 1. 先改变量, 再改组件

如果客户说"我们要把主色从珊瑚改成靛蓝", 改 `--primary` 一处, 全站联动。不要去手动改各处的 `background: #cc785c`。

### 2. 不要引入第四种表面色

Design.md 说: "Cream + coral + dark navy is the trinity. Don't introduce a fourth surface tone."

意思是: **不要画绿色卡片、紫色按钮、橙色背景段落**。如果一定要表达"成功 / 警告 / 错误", 用 `--success` / `--warning` / `--error` 作为**点缀**, 不能成为整片表面。

### 3. 节奏不能塌

相邻两 band 不能同表面色。这是品牌识别的关键节奏。如果你想加新 band, 看上下哪个 surface, 选 alternating 的那个。

## 暗色组件特殊处理

`Design.md` 强调: 暗色面上不要反转用 light secondary 按钮。我们的代码遵守这一点:
- `.product-mockup-card-dark` 内部任何按钮都用 `--surface-dark-elevated` 做背景 (不是 cream)
- 文字用 `--on-dark` (`#faf9f5` cream-tinted white) 不是纯白
- 这让暗色面保持"product chrome"质感, 而不是"反转的 marketing 风"

我们的 stage chip 就是这套规则的典型:
```css
.stage-chip { background: var(--surface-dark-elevated); }
.stage-chip.running { background: var(--surface-dark-soft); border-color: var(--primary); }
.stage-chip.done { border-color: var(--success); }   /* 只换边框,不换底色 */
```

## 响应式坍缩规则

`Design.md` 规定:
- > 1024px: 完整布局 (hero 6/6 grid, feature 3-up)
- 768-1024px: 紧凑 (feature 2-up)
- < 768px: 单列, stage strip 改 2-up

我们的 CSS 用两个断点 (960 / 640) 实现:
```css
@media (max-width: 960px) {
  .hero-grid { grid-template-columns: 1fr; }       /* hero 单列 */
  .two-col { grid-template-columns: 1fr; }          /* obs 单列 */
  .three-up { grid-template-columns: 1fr; }         /* about 单列 */
}
@media (max-width: 640px) {
  .stage-strip { grid-template-columns: repeat(2, 1fr); }  /* stage 改 2-up */
  .field-row { grid-template-columns: 1fr; }
}
```

完全符合 Design.md 的 "feature grids reduce columns rather than scaling cards down" 原则 — 我们改列数, 不缩卡片。

## 验收清单 (给评审用)

打开页面截图, 逐项检查:

- [ ] 背景**不是**纯白, 而是温暖的奶油色
- [ ] 主 CTA "Start extraction" 是**珊瑚色**, 不是蓝色或绿色
- [ ] 标题是**衬线字** (Cormorant Garamond), 不是 Inter
- [ ] 标题字距是**负的** (字母互相靠近一点点), 不是正常字距
- [ ] 字重是 **500 (medium)**, 不是 700 (bold)
- [ ] 卡片圆角是 **12px**, 按钮是 **8px**
- [ ] Section 间距大约 **96px**
- [ ] 暗色 product mockup 卡片 (pipeline + event log) 文字是**奶油色**, 不是纯白
- [ ] 相邻两 band 颜色**不重复** (cream → cream-card → dark → cream...)
- [ ] 没有出现"第四种表面色" (蓝 / 绿 / 紫 / 橙色块)

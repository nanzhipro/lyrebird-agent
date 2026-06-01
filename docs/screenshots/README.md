# Screenshots (V0.2)

四张实拍, 来自真实端到端运行(DeepSeek API 实调), 用 `gstack browse` 在 1440×900 viewport 截。

| 文件 | 时机 |
|---|---|
| `lyrebird-form-clean.png` | 初始页面 — 表单为空 |
| `lyrebird-form-filled.png` | 表单已填(target_role / sample resume / turns / candidate_id) |
| `lyrebird-running.png` | run 中段 — 第 4/7 阶段(mechanism_naming)正在跑, coral 脉动 |
| `lyrebird-final.png` | run 完成 — 7/7 ✓, 11 agent calls 全列表, 报告内联 |
| `lyrebird-zh.png` | i18n: 中文界面全图(默认 locale, V0.3) |
| `lyrebird-en.png` | i18n: 切换到英文后(html lang=en, cookie 持久化) |
| `lyrebird-zh-final.png` | i18n: 中文 + v4 模型, 4 turn run 完成态, 13 LLM 调用零截断 |
| `lyrebird-logo-zh.png` | 琴鸟 logo 集成 + dropdown 切换器(关闭态) — 中文 |
| `lyrebird-dropdown-open.png` | dropdown 打开态, English/中文 列表 + 选中勾标 |
| `lyrebird-logo-en.png` | dropdown 选 English 后的整页效果 |

复现命令:
```bash
uvicorn lyrebird.web.app:app --host 127.0.0.1 --port 8765
# 在另一个 shell:
$B=~/.claude/skills/gstack/browse/dist/browse
$B viewport 1440x900
$B goto http://127.0.0.1:8765/
# 然后手动 click + fill + screenshot
```

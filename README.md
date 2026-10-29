# Foxran Plugin: Meme Stickers（表情包）

Foxran Agent 的表情包插件：维护一个表情包库，让 Agent 在聊天里像真人一样斗图，还能收集别人发的表情包，或者用绘图模型画新的表情包。

## 📦 安装与集成

前往 Foxran WebUI 的 **插件市场 (Marketplace)**，在“工具 (Tool)”分类下点击安装即可。

或者手动通过命令行克隆并安装：
```bash
python scripts/install_market_plugin.py https://github.com/Ainierheokami/foxran-plugin-meme-stickers.git --type tool
```

## 📸 功能说明

- **发表情包**：Agent 在回复里写 `[meme, emotion=happy, tags=开心]`，发送前插件会从库里挑最合适的一张换成图片。
- **收集**：`meme_sticker operation=collect` 把聊天里的图片收进库。宿主 4.8.7 起插件启用时把 `meme_sticker` 登记为核心工具，模型随时能用，不靠向量检索拉起（稳定提示词约多 800 token，可缓存）；更早的宿主照旧靠检索和提示里附的工具说明。同一张图即使 URL 不同（QQ 每次都会换），也会按内容去重并合并标签。
- **生成**：`meme_sticker operation=generate, prompt=画面描述, caption=配字` 调用带 `image_generation` 标签的模型画一张新表情包，自动入库，默认直接发送。
- **复刻**：`meme_sticker operation=remake, url=参考图, prompt=修改要求` 调用带 `image_edit` 标签的模型重画已有表情包（例如“换成狐狸”）；不传 url 时使用最近一条消息里的图片。
- **画她自己**（宿主 4.9.21 起）：在宿主「Agent 人设」页给角色上传形象参考图后，`generate`/`remake` 加 `as_self=true`，会把人设的主图和第二张参考图交给 `image_edit` 模型，照着角色本人的样子画；`remake` 加 `as_self` 会把参考表情包的主角换成她。画好的图自动带上人设名标签。人设有参考图时，表情包机会提示里会告诉 Agent 可以这么用。
- **Prompt 节奏**：
  - 每轮一句能力说明（库里有哪些情绪和标签），Agent 随时可以自己决定发不发；
  - 每隔 `min_messages_between_prompts` 条用户消息，且不在 `cooldown_seconds` 冷却中时，注入“这轮建议发一张”的机会提示；
  - 用户明确要表情包、或自己发来表情包时，不管间隔多少都会提示回一张；
  - 用户发来表情包时提示 Agent 可以收进库；群聊里她没回的消息不会生成提示词，所以她开口时会回看最近 20 条用户消息，把没提过的表情包一并列出（每次最多 3 张）；
  - 消息命中 `blocked_keywords` 时完全不提示。

## 🖥 WebUI（表情包池）

- 主区域是表情网格，顶部可以按文字、标签、情绪、来源和启用状态筛选。没有标注的卡片会显示“未标注”。
- **添加表情包**弹窗：分“本地图片”和“图片链接”两页，可以统一填写说明、情绪和标签，导入前能预览，也能移除不要的图。在页面任意位置拖入图片，或者粘贴图片、图片链接，也会打开这个弹窗。
- **AI 生成**弹窗：分“凭描述生成”和“照参考图复刻”两种模式，并显示绘图模型是否可用、今天已用的额度。勾选“画人设角色本人”/“主角换成人设角色”会照人设形象参考图画。绘图在后台跑（`POST` 立即返回任务，前端轮询 `GET /api/stickers/jobs/{id}`），不会因为反向代理 60 秒超时变成 502/504；作画中可以关掉弹窗，画好会自动入库。
- 点卡片会打开右侧的**详情抽屉**，在里面编辑说明、情绪和标签，启用或停用，用这张图复刻，对单张做 LLM 打标，或者删除。
- 勾选卡片后，底部会出现**批量操作栏**：批量标注（追加或替换标签）、LLM 视觉打标（一次最多 12 张）、启用、停用、删除。已有选中时，点卡片会切换选中状态；按住 Ctrl、⌘ 或 Shift 点击也可以多选。
- 提示和确认框使用宿主的 `window.Foxran.ui.toast` / `confirm`（宿主 4.4.0 及以上）；宿主更早的版本退回浏览器自带的提示。

修改 `web/` 下的源码后，需要在 `web/` 目录执行 `npm install && npm run build` 重新生成 `index.umd.js`（构建前会先跑 `vue-tsc` 类型检查，也可以单独运行 `npm run typecheck`）。

## ⚙️ 配置

配置由插件管理（`backend/config.py`，模板 `config_template.yaml`），保存在宿主配置目录的 `config/meme_sticker.yaml`。插件通过 `configEditors` 向 WebUI 设置页注册可视化编辑器（需要宿主 4.0.0 及以上），也可以切换到源文件直接编辑；直接改文件后，下一轮对话就会生效：

| 段落 | 主要字段 |
| --- | --- |
| `prompt` | `always_show_capability`、`min_messages_between_prompts`、`cooldown_seconds`、`persist_until_sent`、`max_persistent_turns`、`allowed_platforms`、`blocked_keywords` |
| `generation` | `enabled`、`style_prompt`、`size`、`max_per_day`、`hint_enabled` |
| `collection` | `suggest_collect`、`sticker_summary_keywords` |
| `sending` | `max_side`（最长边，默认 384px）、`quality`（默认 72）、`max_kb`（体积上限，默认 1024KB，0 表示不限制）、`max_frames`（动图帧数，默认 48） |

发送时用的是压缩过的 WebP 副本，原图不变。副本超过 `max_kb` 时，先把质量降到 40，再每次把尺寸缩小 20%，直到不超过上限（最长边最小到 64px）。改了 `sending` 以后，每张表情会在下次发送时重新生成副本。只存了外部链接、没有本地文件的表情会原样发送。

生成和复刻需要在 `models.yaml` 里配置带 `image_generation` / `image_edit` 标签的模型；没有可用模型时 prompt 里不会提到生成。

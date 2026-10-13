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
- **收集**：`meme_sticker operation=collect` 把聊天里的图片收进库。同一张图即使 URL 不同（QQ 每次都会换），也会按内容去重并合并标签。
- **生成**：`meme_sticker operation=generate, prompt=画面描述, caption=配字` 调用带 `image_generation` 标签的模型画一张新表情包，自动入库，默认直接发送。
- **复刻**：`meme_sticker operation=remake, url=参考图, prompt=修改要求` 调用带 `image_edit` 标签的模型重画已有表情包（例如“换成狐狸”）；不传 url 时使用最近一条消息里的图片。
- **Prompt 节奏**：
  - 每轮一句能力说明（库里有哪些情绪和标签），Agent 随时可以自己决定发不发；
  - 每隔 `min_messages_between_prompts` 条用户消息，且不在 `cooldown_seconds` 冷却中时，注入“这轮建议发一张”的机会提示；
  - 用户明确要表情包、或自己发来表情包时，不管间隔多少都会提示回一张；
  - 用户发来表情包时提示 Agent 可以收进库；
  - 消息命中 `blocked_keywords` 时完全不提示。

## 🖥 WebUI（表情包池）

- **AI 生成表情包**面板：可以在“生成”和“复刻”之间切换，填写画面描述或修改要求、配字、情绪、标签。面板会显示绘图模型是否可用，以及今天已用的额度。
- 每张卡片都有“复刻”按钮，点一下就把这张图设为参考图；也可以直接填参考图 URL。
- 卡片会标出来源（上传、URL 导入、Agent 收集、AI 生成、AI 复刻），顶部可以按来源筛选。
- 对应接口：`GET /api/stickers/generation/status`、`POST /api/stickers/generate`、`POST /api/stickers/{id}/remake`、`POST /api/stickers/remake`；`GET /api/stickers` 新增 `source` 参数。

修改 `web/` 下的源码后，需要在 `web/` 目录执行 `npm install && npm run build` 重新生成 `index.umd.js`。

## ⚙️ 配置

配置由插件管理（`backend/config.py`，模板 `config_template.yaml`），保存在宿主配置目录的 `config/meme_sticker.yaml`。插件通过 `configEditors` 向 WebUI 设置页注册可视化编辑器（需要宿主 4.0.0 及以上），也可以切换到源文件直接编辑；直接改文件后，下一轮对话就会生效：

| 段落 | 主要字段 |
| --- | --- |
| `prompt` | `always_show_capability`、`min_messages_between_prompts`、`cooldown_seconds`、`persist_until_sent`、`max_persistent_turns`、`allowed_platforms`、`blocked_keywords` |
| `generation` | `enabled`、`style_prompt`、`size`、`max_per_day`、`hint_enabled` |
| `collection` | `suggest_collect`、`sticker_summary_keywords` |

生成和复刻需要在 `models.yaml` 里配置带 `image_generation` / `image_edit` 标签的模型；没有可用模型时 prompt 里不会提到生成。

# Foxran Plugin: Meme Stickers (梗图生成器)

这是一款极具娱乐属性的 Foxran Agent 扩展工具。
当智能体在聊天对话中想要表达情绪时，它可以通过本插件调用底层的图片合成接口，实时将文字动态叠加上自带的表情包模板，并返回多模态的图片结果。

## 📦 安装与集成

前往 Foxran WebUI 的 **插件市场 (Marketplace)**，在“工具 (Tool)”分类下点击安装即可。

或者手动通过命令行克隆并安装：
```bash
python scripts/install_market_plugin.py https://github.com/Foxran/foxran-plugin-meme-stickers.git --type tool
```

## 📸 功能说明

- **动态叠加模板**: 插件自带了多个常用梗图和表情包底图，AI 可以自主选择合适的图片，在指定坐标打上你想要的台词。
- **自包含资源**: 所有的字体文件（如 `simhei.ttf`）和图片模板均打包在插件库内部，开箱即用。
- **自动多模态输出**: Agent 渲染完梗图后，可以将其转换为主框架识别的媒体路径格式，最终以图片形式在 Web 或 QQ 聊天窗口中输出。

## 🛠 开发扩展

如果你想要为插件增加更多的梗图模板，只需：
1. 将你的底图放到插件的 `templates/` 目录。
2. 在工具类实现中添加针对新底图的文字坐标映射逻辑。

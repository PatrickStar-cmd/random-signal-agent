# 海洋插画与背景

欢迎区的鲸鱼与海星使用内置 `image_gen` 工具生成。网页版素材为 `web/ocean-whale.webp`，GitHub Pages 使用相同文件的副本 `docs/images/ocean-whale.webp`；两份内容一致。

原始 PNG 为 1536 × 1024，RGBA、真正透明背景，大小 1,768,376 字节。网页使用保持原尺寸与透明通道的 WebP 编码（quality 90、alphaQuality 100），大小 146,298 字节，约 143 KiB；约比原图小 92%。没有裁剪、重绘或二次去背景。页面通过 object-fit: contain 展示完整插画，手机放在文字下方，避免覆盖标题和按钮。

源 PNG 保留在本机 `outputs/artwork/ocean-whale-source.png`（Git 忽略的工作产物）；生成工具的原始文件仍保留。正常启动不需要生图服务、API Key、图像库或 Node。

## 生成提示词

模式：内置生图工具，新图生成；`transparent_background=true`，未使用 CLI 或参考图片。

```text
Use case: stylized-concept. Asset type: production hero mascot illustration for a cute ocean-themed scientific signal-analysis web application. Generate a NEW original illustration, no source image needs preserving. Subject: a charming baby whale, rounded powder-blue body, pearly ivory belly, glossy friendly dark eyes, subtle pink cheeks, gentle smile, expressive little fins and beautifully curved tail. A tiny coral-pink starfish companion floats beside its tail; a few translucent aqua bubbles and two delicate flowing lilac/aqua signal-wave ribbons underneath. Style: high-quality soft 3D clay illustration, collectible designer toy proportions, fine matte ceramic/velvety texture, subtle iridescent highlights, rich dimensional shading and smooth curves, adorable but refined rather than flat simplistic clip-art. Lighting: diffused studio light from upper left, soft blue/lilac reflections. Palette: powder blue, periwinkle, pale mint, lavender, pearl white and restrained coral pink. Composition: landscape 3:2, centered compact group, full whale body and tail visible, head looking toward left (page text lives to its left), generous transparent margins, composition clearly recognizable when displayed at 350px wide. Genuine transparent alpha background, no white rectangle, no checkerboard baked into pixels, no ocean scenery or pedestal. No text, logos, watermark, human characters, extra whales, hard outlines or distracting tiny detail. Intended for a pale cyan-to-lavender-to-pink gradient banner; shadows should belong to the objects, no large dark ground shadow.
```

## 配色与使用

页面底色由海蓝、薄荷色、薰衣草紫和淡粉色组成多层径向与线性渐变。欢迎区更明亮，带浅色圆环；图表及正文卡片保留清晰的近白色表面。装饰背景不参与任何科学数据绘制。

导航和分区标题使用少量海洋、实验与分析表情，作为 `aria-hidden` 装饰；入口文字与操作名称保持明确。渐变静止，没有新增循环动画或远程素材请求。

## 验证

浏览器检查素材自然宽度为 1536，透明 Alpha 最小值为 0，边角为透明；确认没有白色矩形背景。11 组现有界面流程及 7 种宽度（320–1920 px）的六个分区通过，未出现页面横向溢出或 JavaScript 异常。静态预览同步检查图像加载、尺寸和窄屏布局。

临时脚本、独立服务数据及截图位于 `debug/ocean-artwork/`，说明见 `note.md`；日志覆盖写入 `logs/ocean-artwork/browser.log` 与 `server.log`。此更新及透明 WebP 已包含在 v0.3.0 部署 ZIP 中；图片无需访问外部服务。

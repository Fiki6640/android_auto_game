# Changelog

## [1.0.4] - 2026-07-02

### Added
- **GUI 快速开关**：任务、步骤链、监控项列表改为滑动开关，实时生效无需重启 Bot
- **立即执行按钮**：任务、链、监控项均支持点击“执行”，中断当前任务并立即运行指定项
- **执行后调整（post_adjust）**：任务/链执行后自动修改监控缓存值（如消耗体力、减少队列）
- **步骤链失败重试**：链中某一步失败时重试一次，再次失败则停止该链并继续后续任务
- **高亮当前任务**：GUI 中高亮显示正在执行的任务/链
- **ADB 截图测试脚本**：新增 `test_screenshot.py` 用于单独排查截图问题

### Fixed
- **ADB 截图超时/闪退**：`exec-out screencap -p` 超时后不再因访问 `TimeoutExpired.process` 抛异常
- **ADB 截图兜底**：`exec-out` 失败时自动回退到 `shell screencap + pull`，提高兼容性
- **立即执行闪退**：通过 `_bot_thread_id` 区分新旧线程，避免过期信号干扰
- **开关不生效**：新增 `set_enabled_override` 实现运行时动态启用/禁用

### Changed
- 图标文件从 `图标.png` 重命名为 `icon.png`，打包配置同步更新
- `.gitignore` 增加 `templates/crop*.png` 过滤临时裁剪模板

## [1.0.2] - 之前

### Fixed
- 修复配置文件错误，首次运行自动创建默认配置和模板
- 其他稳定性修复

## [1.0.1]

### Added
- GitHub Actions 打包工作流
- 版本号升级

## [1.0.0]

### Added
- 初始版本：WiFi ADB + OpenCV 模板匹配 + OCR 监控
- PySide6 GUI 界面
- scrcpy 嵌入/静态截图降级

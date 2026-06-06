# Android Bot GUI 界面设计方案

## 概述

为 android-bot 添加 PySide6 GUI 界面：左侧配置面板（device/tasks/chains/monitors），右侧实时截图画面（支持鼠标框选坐标）。

## 当前状态分析

- **bot.py** (584行)：核心逻辑，`GameBot` 类管理 tasks/chains/monitors，`run()` 是阻塞式无限循环
- **config.yaml**：所有配置集中管理，包含 device/tasks/chains/monitors 四大模块
- **ADB 类**：截图、点击、滑动、按键
- **无现有 GUI 代码**

## 设计决策

1. **框架**：PySide6（用户选择）
2. **截图交互**：支持鼠标框选坐标，自动填入配置（用户选择）
3. **架构**：新建 `gui.py` 作为 GUI 入口，不修改 `bot.py` 核心逻辑，通过引用 GameBot 类复用
4. **Bot 运行**：在 QThread 中运行 GameBot，通过信号传递日志/截图/监控数据到 GUI
5. **配置编辑**：直接读写 config.yaml，GUI 修改后保存到文件

## 文件变更

### 1. 新建 `gui.py` — GUI 主程序

#### 整体布局

```
┌──────────────────────────────────────────────────────┐
│  菜单栏: 文件(保存/加载) | 操作(启动/停止/截图)       │
├────────────────────┬─────────────────────────────────┤
│  左侧配置面板       │  右侧截图画面                    │
│  (QScrollArea)     │  (自定义 QLabel)                 │
│                    │                                  │
│  ┌─ 设备设置 ────┐ │  ┌──────────────────────────┐   │
│  │ device IP     │ │  │                          │   │
│  │ interval      │ │  │     实时截图显示          │   │
│  │ threshold     │ │  │     支持鼠标框选          │   │
│  └───────────────┘ │  │                          │   │
│  ┌─ 任务列表 ────┐ │  │                          │   │
│  │ + 添加任务    │ │  └──────────────────────────┘   │
│  │ [帮助] [x]   │ │  ┌──────────────────────────┐   │
│  │ [关闭聊天][x] │ │  │ 坐标信息栏               │   │
│  └───────────────┘ │  │ 框选: (x1,y1)-(x2,y2)   │   │
│  ┌─ 步骤链 ─────┐ │  │ 鼠标: (x, y)             │   │
│  │ + 添加链     │ │  └──────────────────────────┘   │
│  │ [治疗] [x]   │ │                                  │
│  │ [打巨兽] [x]  │ │                                  │
│  └───────────────┘ │                                  │
│  ┌─ 监控项 ─────┐ │                                  │
│  │ + 添加监控   │ │                                  │
│  │ [队列检测][x] │ │                                  │
│  │ [体力检测][x] │ │                                  │
│  └───────────────┘ │                                  │
│  ┌─ 日志 ───────┐ │                                  │
│  │ (滚动日志)   │ │                                  │
│  └───────────────┘ │                                  │
├────────────────────┴─────────────────────────────────┤
│  状态栏: 设备状态 | Bot状态 | 监控数值               │
└──────────────────────────────────────────────────────┘
```

#### 核心类

**`BotThread(QThread)`** — 在子线程中运行 GameBot
- 信号：`log_signal(str)`, `screenshot_signal(str)`, `monitor_signal(dict)`, `status_signal(str)`
- 通过修改 GameBot 的 log handler 和截图回调来获取数据
- 支持 start/stop 控制

**`ScreenshotWidget(QLabel)`** — 右侧截图显示+框选
- 显示当前截图（按比例缩放）
- 鼠标移动时显示坐标（映射回原始分辨率）
- 鼠标拖拽框选区域，释放时弹出菜单：设为 region / 设为 pre_tap / 复制坐标
- 坐标映射：显示尺寸 → 原始截图尺寸

**`ConfigPanel(QWidget)`** — 左侧配置面板
- **设备设置组**：device, interval, threshold, adb_path 输入框
- **任务列表组**：QListWidget 显示任务，双击编辑，支持添加/删除/启用切换
- **步骤链组**：QTreeWidget 显示链和步骤，双击编辑，支持添加/删除/启用切换
- **监控项组**：QListWidget 显示监控，双击编辑，支持添加/删除/启用切换
- **日志组**：QTextEdit 只读，实时显示 bot 日志

**`TaskEditDialog(QDialog)`** — 任务/步骤编辑对话框
- 表单式编辑：name, template(文件选择), action(下拉), offset_x/y, cooldown, max_triggers, threshold

**`ChainEditDialog(QDialog)`** — 链编辑对话框
- 链属性：name, enabled, reset_timeout, skip_conditions, close_template
- 步骤列表：可添加/删除/排序步骤，每个步骤用 TaskEditDialog 编辑

**`MonitorEditDialog(QDialog)`** — 监控编辑对话框
- 表单：name, region(4个坐标输入+从截图框选按钮), pre_tap, fixed_total, report, interval, alert_threshold, close_template

**`MainWindow(QMainWindow)`** — 主窗口
- 组装所有组件
- 菜单栏：保存配置、加载配置、启动/停止Bot、手动截图
- 状态栏：设备连接状态、Bot运行状态、监控数值显示
- 配置加载/保存：读写 config.yaml

#### 关键交互流程

1. **启动**：加载 config.yaml → 填充左侧面板 → 用户可编辑
2. **运行Bot**：保存配置 → 创建 GameBot → 启动 BotThread → 日志/截图实时更新到 GUI
3. **截图框选**：右侧画面鼠标拖拽 → 弹出菜单选择用途 → 自动填入左侧对应配置
4. **停止Bot**：停止 BotThread → 状态更新
5. **保存配置**：从左侧面板收集数据 → 写入 config.yaml

### 2. 修改 `bot.py` — 最小改动

- 在 `GameBot.__init__` 中添加可选的回调参数 `on_screenshot=None`
- 在 `run()` 循环中截图后调用回调（如果存在），用于 GUI 获取截图路径
- 在日志 handler 中添加可选的回调，用于 GUI 捕获日志
- **不改变**现有命令行运行方式，GUI 和 CLI 共存

### 3. 修改 `pyproject.toml` — 添加依赖

```toml
dependencies = [
    "opencv-python-headless",
    "numpy",
    "pyyaml",
    "rapidocr-onnxruntime",
    "PySide6",
]
```

### 4. 修改 `启动Bot.bat` — 添加 GUI 启动选项

```
选择模式:
[1] 命令行模式
[2] 图形界面模式
```

## 实现步骤

1. 添加 PySide6 依赖
2. 修改 bot.py 添加回调支持（on_screenshot, on_log）
3. 创建 gui.py：
   - ScreenshotWidget（截图显示+框选）
   - BotThread（子线程运行 GameBot）
   - ConfigPanel（左侧配置面板+各编辑对话框）
   - MainWindow（主窗口组装）
   - 入口 `if __name__ == "__main__"`
4. 更新启动脚本

## 验证步骤

1. `uv sync` 安装 PySide6
2. `python gui.py` 启动 GUI
3. 验证：加载 config.yaml、编辑配置、截图显示、鼠标框选坐标、启动/停止 Bot
4. 验证：`python bot.py` 命令行模式仍正常工作

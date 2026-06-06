# GUI 改进方案：scrcpy 实时画面 + 弹窗截图框选

## 概述

1. 右侧画面改为 scrcpy 实时流（嵌入主窗口）
2. "从截图框选/截取/选取"改为弹出独立截图窗口，在弹窗上操作

## 当前状态分析

- **ScreenshotWidget**：QLabel 显示静态截图，支持鼠标框选
- **框选流程**：编辑对话框关闭(done(Rejected)) → 主窗口进入 pick 模式 → 用户在截图上操作 → 重新打开对话框
- **问题**：嵌套对话框(ChainEditDialog→TaskEditDialog→"从截图截取")时，Rejected 会关闭整条对话框链，数据丢失；且用户反馈按钮无效
- **ADB**：仅 `screenshot()` 做一次性截图，无实时流
- **scrcpy**：项目中未使用

## 设计决策

1. **scrcpy 嵌入主窗口**：使用 `QProcess` 启动 scrcpy，通过 `--window-id` 嵌入到右侧 QWidget
2. **弹窗截图框选**：点击"从截图框选"等按钮时，先截图，弹出 `ScreenshotPickDialog`（独立窗口），在弹窗上框选/点击，完成后自动填回编辑对话框
3. **保留手动截图**：scrcpy 仅做显示，截图仍用 ADB screencap（保证分辨率准确）

## 文件变更

### 1. 修改 `gui.py`

#### 新增 `ScrcpyWidget(QWidget)`

替代原 `ScreenshotWidget` 作为右侧画面容器：

```python
class ScrcpyWidget(QWidget):
    """嵌入 scrcpy 实时画面"""
    def __init__(self, parent=None):
        super().__init__()
        self._process = None  # QProcess
        self._container = QWidget()  # scrcpy 嵌入的目标 widget

    def start(self, device: str, adb_path: str = "adb"):
        """启动 scrcpy 进程，嵌入到 _container"""
        # scrcpy --window-id=<WId> --no-audio --max-size=800 --stay-awake
        self._process = QProcess(self)
        self._process.setProcessArguments([...])
        self._process.start("scrcpy", [...])

    def stop(self):
        """停止 scrcpy"""
        if self._process:
            self._process.terminate()

    def is_running(self) -> bool:
        return self._process and self._process.state() == QProcess.Running
```

关键参数：
- `--window-id=<WId>`：将 scrcpy 窗口嵌入 Qt widget（通过 `self._container.winId()`）
- `--no-audio`：不需要音频
- `--max-size=800`：限制分辨率，减少带宽
- `--stay-awake`：保持屏幕常亮
- `--turn-screen-off`：手机端关闭屏幕（可选）

#### 新增 `ScreenshotPickDialog(QDialog)`

弹窗式截图框选/点击选取：

```python
class ScreenshotPickDialog(QDialog):
    """弹出截图框选/点击对话框"""
    # mode: "region" | "point"
    # 完成后通过信号返回坐标

    region_picked = Signal(int, int, int, int)  # x1, y1, x2, y2
    point_picked = Signal(int, int)              # x, y

    def __init__(self, screenshot_path: str, mode: str = "region", parent=None):
        # 加载截图到 QLabel（复用 ScreenshotWidget 的缩放/坐标映射逻辑）
        # mode="region": 鼠标拖拽框选
        # mode="point": 鼠标点击选取
        # 框选/点击完成后自动关闭，发射信号
```

流程：
1. 用户点击"从截图框选" → 先调用 ADB 截图 → 创建 `ScreenshotPickDialog(mode="region")`
2. 弹窗显示最新截图，用户框选/点击
3. 弹窗关闭，信号携带坐标返回
4. 坐标自动填入编辑对话框（编辑对话框不关闭！）

#### 修改编辑对话框

**MonitorEditDialog**：
- "从截图框选"按钮：截图 → 弹出 `ScreenshotPickDialog(mode="region")` → 信号连接到填入 region_edits
- "从截图选取"按钮：截图 → 弹出 `ScreenshotPickDialog(mode="point")` → 信号连接到填入 pretap_x/y
- **不再关闭编辑对话框**

**TaskEditDialog**：
- "从截图截取"按钮：截图 → 弹出 `ScreenshotPickDialog(mode="region")` → 信号连接到裁剪保存模板 + 填入 template_edit
- **不再关闭编辑对话框**

#### 修改 MainWindow

- 右侧 `ScreenshotWidget` 替换为 `ScrcpyWidget`
- 启动 Bot 时同时启动 scrcpy
- 停止 Bot 时同时停止 scrcpy
- 手动截图功能保留（ADB screencap）
- 移除 `_pick_mode` 相关逻辑（不再需要，框选在弹窗中完成）
- 新增菜单项：启动/停止 scrcpy（可独立于 Bot）

#### 保留 `ScreenshotWidget` 类

重命名为 `_ScreenshotCanvas`，作为 `ScreenshotPickDialog` 的内部组件，复用缩放和坐标映射逻辑。

### 2. 修改 `bot.py`

- ADB 类新增 `get_screenshot_bytes()` 方法，返回 PNG bytes（供 GUI 直接使用，无需写文件）
- 最小改动，不影响命令行模式

### 3. 修改 `config.yaml`

新增可选配置：

```yaml
scrcpy:
  enabled: true
  path: "scrcpy"          # scrcpy 可执行文件路径
  max_size: 800            # 最大分辨率
  extra_args: ""           # 额外参数
```

## 实现步骤

1. 重构 `ScreenshotWidget` → `_ScreenshotCanvas`（内部组件）
2. 新增 `ScreenshotPickDialog`（弹窗截图框选）
3. 修改 `MonitorEditDialog` / `TaskEditDialog`：使用弹窗框选，不再关闭自身
4. 新增 `ScrcpyWidget`（嵌入 scrcpy）
5. 修改 `MainWindow`：右侧替换为 ScrcpyWidget，移除 pick_mode 逻辑
6. 修改 `config.yaml`：添加 scrcpy 配置
7. 修改 `bot.py`：ADB 新增 `get_screenshot_bytes()`

## 验证步骤

1. 启动 GUI，scrcpy 嵌入右侧正常显示
2. 点击"从截图框选"→ 弹窗出现 → 框选 → 坐标填入
3. 点击"从截图截取"→ 弹窗出现 → 框选 → 模板裁剪保存 + 路径填入
4. 启动/停止 Bot 正常
5. scrcpy 未安装时降级为静态截图模式

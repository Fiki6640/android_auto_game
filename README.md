## 无尽冬日 - 自动化 Bot

基于 WiFi ADB + OpenCV 模板匹配 + OCR 的 Android 游戏自动化工具，支持 PySide6 GUI 界面。

### 📁 目录结构
```
android-bot/
├── bot.py                # Bot 核心逻辑（ADB、模板匹配、OCR、监控）
├── gui.py                # PySide6 GUI 界面
├── config.yaml           # 配置文件（改这里）
├── test_screenshot.py    # ADB 截图单独测试脚本
├── pyproject.toml        # 项目依赖
├── requirements.txt
├── build.spec            # PyInstaller 打包配置
├── 启动Bot.bat           # Windows 双击启动
├── icon.png              # 应用图标
├── templates/            # 模板图片（按钮截图）
└── screenshots/          # 运行时截图（调试用）
```

### 🆕 最近更新

- **GUI 快速开关**：任务、步骤链、监控项列表改为滑动开关，实时生效无需重启 Bot
- **立即执行按钮**：任务、链、监控项均支持点击“执行”，中断当前任务并立即运行指定项
- **执行后调整（post_adjust）**：任务/链执行后自动修改监控缓存值（如消耗体力、减少队列）
- **步骤链失败重试**：链中某一步失败时重试一次，再次失败则停止该链并继续后续任务
- **高亮当前任务**：GUI 中高亮显示正在执行的任务/链
- **ADB 截图兜底**：`exec-out` 超时失败时自动回退到“保存到设备再 pull”，避免 Bot 卡死
- **ADB 截图测试脚本**：新增 `test_screenshot.py` 用于单独排查截图问题

---

### 🔧 第一步：开启手机无线调试

1. 手机 **设置 → 关于手机 → 版本号**（狂点7次）→ 开启开发者选项
2. **设置 → 开发者选项 → 无线调试**，打开它
3. 记下显示的 **IP 地址和端口**（如 `192.168.1.100:5555`）

> ⚠️ Android 11+ 的无线调试端口是动态的（不一定是5555），要看屏幕上显示的端口

---

### ✏️ 第二步：填写配置

打开 `config.yaml`，修改第一行：
```yaml
device: "192.168.1.100:5555"   # 改成你的 IP:端口
```

---

### 🖼️ 第三步：制作模板图片

**方法A：GUI 界面中"从截图截取"**

编辑任务/步骤/监控项时，点击"从截图截取"按钮，自动截图并在弹窗中框选区域，裁剪保存为模板。

**方法B：命令行截图，再裁剪**
```bash
python bot.py --capture
```
会在 `screenshots/` 生成一张截图，用 **Snipaste / 画图 / PS** 裁剪出你要识别的按钮，保存到 `templates/` 目录。

**方法C：直接截手机屏幕**
```bash
adb -s 你的IP:端口 exec-out screencap -p > screen.png
```

**模板图片要求：**
- 格式：PNG 或 JPG
- 尽量只截**按钮本身**，不要包含太多背景
- 分辨率和手机实际显示一致（不要缩放）

---

### 🚀 第四步：启动

**方式一：双击** `启动Bot.bat`

**方式二：命令行**
```bash
cd android-bot
uv run gui.py
```

**方式三：打包后直接运行**
```bash
# 打包
uv run pyinstaller build.spec
# 运行
dist/无尽冬日-自动化.exe
```

**测试模板匹配效果：**
```bash
python bot.py --test screenshots/current.png templates/你的按钮.png
```

---

### 🖥️ GUI 界面说明

启动后自动运行 Bot，界面分为：

- **左侧**：配置面板（设备、任务、步骤链、监控项）
  - 每项右侧有**滑动开关**，点击立即启用/禁用，无需重启 Bot
  - 每项右侧有**执行按钮**，点击会中断当前任务并立即执行该项
  - 双击项目可编辑详情（模板、坐标、post_adjust 等）
- **右侧**：scrcpy 实时画面 / 静态截图
- **右上角控制按钮**：关屏（熄灭手机屏幕仅电脑显示）、Home、返回、多任务
- **状态栏**：显示体力、剩余队列等监控数据

**高亮**：正在执行的任务/链会在列表中高亮显示。

**关屏说明**：优先通过 scrcpy 快捷键（Alt+O）实现原生关屏，电源键可正常恢复；scrcpy 未嵌入时降级为亮度方式。

---

### 📦 打包

使用 PyInstaller 打包为单个 exe 文件：

```bash
uv run pyinstaller build.spec
```

打包产物在 `dist/无尽冬日-自动化.exe`，运行时需要同目录下有 `config.yaml` 和 `templates/` 文件夹。

---

### ⚙️ 配置说明

#### 基础参数

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `device` | 设备 IP:端口 | 你的手机地址 |
| `threshold` | 匹配阈值，越高越严格 | 0.85 ~ 0.90 |
| `interval` | 检查间隔（秒） | 0.3 ~ 2.0 |
| `adb_path` | adb 可执行文件路径 | adb |

#### 任务 (tasks)

独立触发的动作，每次循环检测屏幕，匹配到模板就执行动作。

```yaml
tasks:
  - name: "帮助"
    enabled: true
    template: templates/help.png
    action: tap          # 动作类型
    offset_x: 0
    offset_y: 0
    cooldown: 0.3
    max_triggers: 0      # 0=无限
    post_adjust:         # 执行后调整监控值（可选）
      - "体力检测 current -30"
      - "队列检测 value -1"
```

**动作类型：**

| 中文 | 英文值 | 说明 |
|------|--------|------|
| 点击匹配区域 | tap | 点击模板匹配位置 |
| 点击指定坐标 | tap_coord | 点击 x, y 坐标 |
| 按键 | keyevent | 发送按键码（如4=返回） |

#### 步骤链 (chains)

按顺序执行的步骤序列，用于复杂操作流程。

```yaml
chains:
  - name: "打巨兽"
    enabled: true
    reset_timeout: 10
    skip_conditions:     # 跳过条件（满足任一则跳过整条链）
      - monitor: "体力检测"
        field: current
        op: "<"
        value: 25
    steps:
      - template: templates/1.png
        action: tap
        cooldown: 0.3
        skippable: true  # 识别不到时跳过此步骤
      - template: templates/2.png
        action: tap
        cooldown: 0.1
    close_template: templates/x.png  # 执行完毕后关闭页面
    post_adjust:         # 执行后调整监控值（可选）
      - "体力检测 current -25"
```

**skippable**：设为 true 时，如果此步骤的模板在屏幕上找不到，自动跳到下一步，避免链卡住。

**失败重试**：链中某一步匹配失败后，会自动重试一次；再次失败则停止该链并继续后续任务。

#### 监控项 (monitors)

OCR 数值检测，用于监控体力、队列等数据。

```yaml
monitors:
  - name: "体力检测"
    enabled: true
    pre_type: tap              # 前置操作类型：none/tap/template
    pre_tap: [92, 186]         # pre_type=tap 时：前置点击坐标
    region: [228, 2862, 384, 2916]  # OCR 识别区域
    fixed_total: 200           # 固定总值（0=自动识别）
    report: current            # 报告类型：current(当前值)/remaining(剩余值)
    interval: 60               # 检测间隔（秒）
    alert_threshold: 25        # 低于此值发出警告（0=关闭）
    close_template: templates/close.png  # 检测后关闭页面

  - name: "队列检测"
    enabled: true
    pre_type: template         # 前置操作：区域匹配
    pre_template: templates/queue_btn.png  # 前置匹配模板
    pre_skippable: false       # 前置匹配失败时是否跳过本次监控
    region: [401, 511, 484, 597]
    report: remaining          # 报告剩余值（total - current）
    interval: 5
```

**前置操作类型 (pre_type)：**

| 类型 | 说明 |
|------|------|
| `none` | 无前置操作 |
| `tap` | 点击指定坐标（如打开体力页面） |
| `template` | 模板匹配区域，匹配成功则点击（如点击队列按钮），失败时根据 `pre_skippable` 决定是否跳过 |

**报告类型 (report)：**

| 类型 | 说明 |
|------|------|
| `current` | 报告当前值（如体力 126/200 → 126） |
| `remaining` | 报告剩余值（如队列 3/4 → 1） |

#### 执行后调整 (post_adjust)

任务或步骤链执行完毕后，可以按规则修改监控项的缓存值，避免频繁 OCR。

```yaml
post_adjust:
  - "体力检测 current -30"   # 体力检测的 current 减 30
  - "队列检测 value -1"      # 队列检测的 value 减 1
```

格式：`监控名 字段 操作数值`，字段支持 `current`、`total`、`value`，操作只支持 `+` 或 `-`。

#### scrcpy 配置

```yaml
scrcpy:
  enabled: true
  path: scrcpy       # scrcpy 可执行文件路径
  max_size: 800      # 最大画面尺寸
```

---

### 🐛 常见问题

**Q: adb 找不到设备**
- 确认手机和电脑在同一 WiFi
- 重新开关手机的「无线调试」
- 检查 IP 和端口是否正确

**Q: 匹配失败（置信度很低）**
- 重新截模板图，确保和游戏运行时按钮一致
- 降低 threshold（如改为 0.75）
- 检查游戏是否有动态效果导致按钮变化

**Q: 点击位置偏移**
- 用 `offset_x` / `offset_y` 微调
- 或重新裁剪更精确的模板

**Q: 游戏有缩放/分辨率不同**
- 模板必须在**同一分辨率**下截取
- 如手机是 2K 屏，模板也要 2K 分辨率截图

**Q: OCR 识别错误（多识别一位数字）**
- 使用 `fixed_total` 指定固定总值，自动修正多识别的数字
- OCR 识别失败时会自动重试 3 次

**Q: scrcpy 无法启动**
- 确认 scrcpy 已安装并在 PATH 中
- GUI 会自动降级为静态截图模式

**Q: 关屏后电源键无法恢复**
- scrcpy 嵌入时使用原生快捷键关屏，电源键可正常恢复
- scrcpy 未嵌入时降级为亮度方式，电源键也可恢复

**Q: ADB 截图卡顿或超时**
- Bot 已内置兜底：快路径 `exec-out` 失败时会自动改用 `shell screencap + pull`
- 可单独测试 ADB 截图：
  ```bash
  python test_screenshot.py --count 5
  ```
- 如果截图一直失败，尝试重新开关手机的「无线调试」或重启 WiFi

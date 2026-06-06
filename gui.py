#!/usr/bin/env python3
"""
Android Bot GUI - PySide6 图形界面
左侧：配置面板（device/tasks/chains/monitors）
右侧：scrcpy 实时画面（降级为静态截图）
截图框选：弹出独立窗口
"""

import os
import sys
import time
import yaml
import threading
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QGroupBox, QFormLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QCheckBox, QPushButton, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel, QComboBox,
    QDialog, QDialogButtonBox, QFileDialog, QMenu, QMenuBar,
    QStatusBar, QScrollArea, QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QThread, QRect, QPoint, QProcess, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QAction, QCursor, QIcon

# 动作类型：中文显示 -> 英文值
ACTION_LABELS = {
    "点击匹配区域": "tap",
    "点击固定坐标": "tap_coord",
    "滑动(Todo)": "swipe",
    "按键(Todo)": "key",
}
ACTION_VALUES = {v: k for k, v in ACTION_LABELS.items()}

# 报告类型：中文显示 -> 英文值
REPORT_LABELS = {
    "当前值(分子)": "current",
    "剩余值(分母-分子)": "remaining",
}
REPORT_VALUES = {v: k for k, v in REPORT_LABELS.items()}


# ==================== 截图画布（内部组件）====================

class _ScreenshotCanvas(QLabel):
    """截图显示画布，支持鼠标框选/点击，用于弹窗框选"""

    region_selected = Signal(int, int, int, int)
    point_clicked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #1a1a2e; border: 1px solid #333;")
        self.setText("等待截图...")

        self._pixmap = None
        self._orig_size = (1080, 2400)
        self._scale = 1.0
        self._offset = QPoint(0, 0)
        self._selecting = False
        self._start_pos = None
        self._current_pos = None  # 当前鼠标位置（用于绘制选择框）

    def set_screenshot(self, path: str):
        img = QImage(path)
        if img.isNull():
            return
        self._orig_size = (img.width(), img.height())
        self._pixmap = QPixmap.fromImage(img)
        self._update_display()

    def _update_display(self):
        if not self._pixmap:
            return
        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._scale = scaled.width() / self._orig_size[0]
        self._offset = QPoint(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
        )
        self.setPixmap(scaled)

    def _display_to_orig(self, pos: QPoint) -> QPoint:
        x = int((pos.x() - self._offset.x()) / self._scale)
        y = int((pos.y() - self._offset.y()) / self._scale)
        x = max(0, min(x, self._orig_size[0] - 1))
        y = max(0, min(y, self._orig_size[1] - 1))
        return QPoint(x, y)

    def paintEvent(self, event):
        super().paintEvent(event)
        # 绘制选择框
        if self._selecting and self._start_pos and self._current_pos:
            painter = QPainter(self)
            pen = QPen(QColor(0, 255, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            rect = QRect(self._start_pos, self._current_pos).normalized()
            painter.drawRect(rect)
            painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pixmap:
            self._selecting = True
            self._start_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._pixmap and self._selecting and self._start_pos:
            self._current_pos = event.position().toPoint()
            self.update()  # 触发 paintEvent 重绘选择框

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._selecting and self._start_pos:
            self._selecting = False
            self._current_pos = None
            end_pos = event.position().toPoint()
            orig_start = self._display_to_orig(self._start_pos)
            orig_end = self._display_to_orig(end_pos)

            x1, y1 = orig_start.x(), orig_start.y()
            x2, y2 = orig_end.x(), orig_end.y()
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)

            dist = abs(x2 - x1) + abs(y2 - y1)
            if dist < 5:
                self.point_clicked.emit(x1, y1)
            else:
                self.region_selected.emit(x1, y1, x2, y2)

            self._start_pos = None
            self._update_display()


# ==================== 弹窗截图框选 ====================

class ScreenshotPickDialog(QDialog):
    """弹出截图框选/点击对话框，完成后自动关闭并发射信号"""

    region_picked = Signal(int, int, int, int)  # x1, y1, x2, y2
    point_picked = Signal(int, int)              # x, y

    def __init__(self, screenshot_path: str, mode: str = "region", parent=None):
        super().__init__(parent)
        self.setWindowTitle("框选区域" if mode == "region" else "选取坐标")
        self.setMinimumSize(400, 700)
        self.resize(500, 850)
        self._mode = mode

        layout = QVBoxLayout(self)

        # 提示
        if mode == "region":
            hint = "请在截图上拖拽框选区域，松开鼠标自动确认"
        else:
            hint = "请在截图上点击选取坐标"
        hint_label = QLabel(hint)
        hint_label.setStyleSheet("padding: 6px; background: #1a5276; color: #f9e79f; font-weight: bold;")
        layout.addWidget(hint_label)

        # 截图画布
        self.canvas = _ScreenshotCanvas()
        self.canvas.set_screenshot(screenshot_path)
        if mode == "region":
            self.canvas.region_selected.connect(self._on_region)
        else:
            self.canvas.point_clicked.connect(self._on_point)
        layout.addWidget(self.canvas, 1)

        # 坐标显示
        self.coord_label = QLabel("鼠标: (-, -)")
        self.coord_label.setStyleSheet("padding: 4px; background: #2d2d2d; color: #aaa; font-family: Consolas;")
        layout.addWidget(self.coord_label)

        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        # 鼠标移动更新坐标
        self.canvas.setMouseTracking(True)
        self._orig_mouse_move = self.canvas.mouseMoveEvent
        self.canvas.mouseMoveEvent = self._tracked_mouse_move

    def _tracked_mouse_move(self, event):
        if self.canvas._pixmap:
            orig = self.canvas._display_to_orig(event.position().toPoint())
            self.coord_label.setText(f"鼠标: ({orig.x()}, {orig.y()})")
        # 调用原始的 mouseMoveEvent 处理框选绘制
        self._orig_mouse_move(event)

    def _on_region(self, x1, y1, x2, y2):
        self.coord_label.setText(f"框选: ({x1},{y1})-({x2},{y2})")
        self.region_picked.emit(x1, y1, x2, y2)
        self.accept()

    def _on_point(self, x, y):
        self.coord_label.setText(f"选取: ({x}, {y})")
        self.point_picked.emit(x, y)
        self.accept()


# ==================== Scrcpy 嵌入组件 ====================

class ScrcpyWidget(QWidget):
    """嵌入 scrcpy 实时画面，降级为静态截图"""

    log_message = Signal(str)  # 发送日志消息到主窗口

    # 嵌入窗口的唯一标题，用于查找 scrcpy 窗口
    _EMBED_TITLE = "scrcpy-embed-android-bot"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._scrcpy_available = None  # None=未检测, True/False
        self._device = ""
        self._adb_path = "adb"
        self._scrcpy_path = "scrcpy"
        self._max_size = 800
        self._last_screenshot = None
        self._embedded_hwnd = None
        self._embed_timer = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 画面区域（带叠加控制按钮）
        self._view_stack = QWidget()
        view_layout = QVBoxLayout(self._view_stack)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)

        # scrcpy 嵌入容器
        self._container = QWidget()
        self._container.setMinimumSize(360, 640)
        self._container.setStyleSheet("background-color: #1a1a2e;")
        view_layout.addWidget(self._container, 1)

        # 降级模式：静态截图显示
        self._fallback_canvas = _ScreenshotCanvas()
        self._fallback_canvas.hide()
        view_layout.addWidget(self._fallback_canvas, 1)

        # 右上角叠加控制按钮
        self._ctrl_bar = QWidget(self._view_stack)
        self._ctrl_bar.setStyleSheet(
            "QPushButton { background: rgba(45,45,45,200); color: #ddd; border: 1px solid #555; "
            "border-radius: 4px; padding: 4px 10px; font-size: 13px; }"
            "QPushButton:hover { background: rgba(80,80,80,220); }"
            "QPushButton:pressed { background: rgba(120,120,120,220); }"
        )
        ctrl_layout = QHBoxLayout(self._ctrl_bar)
        ctrl_layout.setContentsMargins(4, 4, 4, 4)
        ctrl_layout.addStretch()

        btn_power = QPushButton("⏻ 关屏")
        btn_power.setToolTip("熄灭手机屏幕，仅在电脑显示画面（再点恢复）")
        btn_power.setCheckable(True)
        btn_power.clicked.connect(self._toggle_screen_off)

        btn_home = QPushButton("⌂ Home")
        btn_home.setToolTip("Home 键 (KEYCODE_HOME)")
        btn_home.clicked.connect(lambda: self._adb_keyevent(3))

        btn_back = QPushButton("← 返回")
        btn_back.setToolTip("返回键 (KEYCODE_BACK)")
        btn_back.clicked.connect(lambda: self._adb_keyevent(4))

        btn_recent = QPushButton("□ 多任务")
        btn_recent.setToolTip("最近任务键 (KEYCODE_APP_SWITCH)")
        btn_recent.clicked.connect(lambda: self._adb_keyevent(187))

        for btn in (btn_power, btn_home, btn_back, btn_recent):
            ctrl_layout.addWidget(btn)

        layout.addWidget(self._view_stack, 1)

        # 状态标签
        self._status_label = QLabel("等待连接...")
        self._status_label.setStyleSheet(
            "padding: 4px; background: #2d2d2d; color: #aaa; font-family: Consolas;"
        )
        layout.addWidget(self._status_label)

    def _check_scrcpy(self) -> bool:
        """检测 scrcpy 是否可用"""
        if self._scrcpy_available is not None:
            return self._scrcpy_available
        try:
            import subprocess
            result = subprocess.run(
                [self._scrcpy_path, "--version"],
                capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                self._scrcpy_available = True
                version = result.stdout.decode("utf-8", errors="replace").strip()
                self._status_label.setText(f"scrcpy 可用: {version[:60]}")
            else:
                self._scrcpy_available = False
                err = result.stderr.decode("utf-8", errors="replace").strip()
                self._status_label.setText(f"scrcpy 不可用 (exit={result.returncode}): {err[:80]}")
        except FileNotFoundError:
            self._scrcpy_available = False
            self._status_label.setText(f"scrcpy 未找到: '{self._scrcpy_path}' 不在 PATH 中")
        except Exception as e:
            self._scrcpy_available = False
            self._status_label.setText(f"scrcpy 检测失败: {e}")
        return self._scrcpy_available

    def start(self, device: str, adb_path: str = "adb", scrcpy_path: str = "scrcpy",
              max_size: int = 800):
        """启动 scrcpy 或降级为静态截图"""
        self._device = device
        self._adb_path = adb_path
        self._scrcpy_path = scrcpy_path
        self._max_size = max_size

        if self._check_scrcpy():
            self._start_scrcpy()
        else:
            self._start_fallback()

    def _start_scrcpy(self):
        """启动 scrcpy 并嵌入到容器中"""
        self._fallback_canvas.hide()
        self._container.show()

        self._process = QProcess(self)
        self._process.finished.connect(self._on_scrcpy_finished)
        self._process.errorOccurred.connect(self._on_scrcpy_error)

        # 收集 scrcpy 输出用于调试
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_scrcpy_output)

        args = [
            "--serial", self._device,
            "--no-audio",
            "--max-size", str(self._max_size),
            "--stay-awake",
            "--window-title", self._EMBED_TITLE,
        ]

        cmd_str = f"{self._scrcpy_path} {' '.join(args)}"
        self._status_label.setText(f"启动 scrcpy...")
        self.log_message.emit(f"[scrcpy] 启动: {cmd_str}")

        self._process.start(self._scrcpy_path, args)

        # 启动定时器查找并嵌入 scrcpy 窗口
        self._embedded_hwnd = None
        if self._embed_timer:
            self._embed_timer.stop()
        self._embed_timer = QTimer(self)
        self._embed_timer.timeout.connect(self._try_embed_scrcpy)
        self._embed_timer.start(200)  # 每200ms尝试一次

    def _try_embed_scrcpy(self):
        """尝试查找 scrcpy 窗口并嵌入到容器中"""
        if self._embedded_hwnd:
            # 已嵌入，调整大小
            self._resize_embedded()
            return

        if sys.platform != "win32":
            # 非 Windows 不支持嵌入，停止定时器
            self._embed_timer.stop()
            self._status_label.setText("scrcpy 已在独立窗口启动")
            return

        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, self._EMBED_TITLE)
            if hwnd:
                self._embedded_hwnd = hwnd
                container_hwnd = int(self._container.winId())

                # 嵌入窗口
                ctypes.windll.user32.SetParent(hwnd, container_hwnd)
                # 移除窗口边框
                GWL_STYLE = -16
                WS_CHILD = 0x40000000
                WS_VISIBLE = 0x10000000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
                style = (style & ~0x00CF0000) | WS_CHILD | WS_VISIBLE  # 去掉标题栏等
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)

                self._resize_embedded()
                self._status_label.setText("scrcpy 已嵌入")
                self.log_message.emit("[scrcpy] 窗口已嵌入主界面")
                self._embed_timer.stop()
        except Exception as e:
            self.log_message.emit(f"[scrcpy] 嵌入失败: {e}")

    def _resize_embedded(self):
        """调整嵌入窗口大小以适应容器"""
        if not self._embedded_hwnd or sys.platform != "win32":
            return
        try:
            import ctypes
            w = self._container.width()
            h = self._container.height()
            ctypes.windll.user32.MoveWindow(self._embedded_hwnd, 0, 0, w, h, True)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._embedded_hwnd:
            self._resize_embedded()
        self._position_ctrl_bar()

    def _position_ctrl_bar(self):
        """将控制按钮栏定位到右上角"""
        if hasattr(self, '_ctrl_bar'):
            bar = self._ctrl_bar
            bar.adjustSize()
            x = self._view_stack.width() - bar.width() - 4
            bar.move(x, 4)

    def _adb_keyevent(self, keycode: int):
        """通过 ADB 发送按键事件"""
        if not self._device:
            self.log_message.emit("[ADB] 未设置设备，无法发送按键")
            return
        try:
            import subprocess
            cmd = [self._adb_path, "-s", self._device, "shell", "input", "keyevent", str(keycode)]
            subprocess.run(cmd, timeout=5,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            key_names = {3: "HOME", 4: "BACK", 187: "APP_SWITCH"}
            name = key_names.get(keycode, str(keycode))
            self.log_message.emit(f"[ADB] 按键: {name}")
        except Exception as e:
            self.log_message.emit(f"[ADB] 按键失败: {e}")

    def _toggle_screen_off(self, checked: bool):
        """切换手机屏幕显示：熄灭手机屏幕但保持系统运行，电脑端仍可看到画面"""
        if not self._device:
            self.log_message.emit("[ADB] 未设置设备，无法操作")
            return
        try:
            import subprocess
            if checked:
                # 熄灭屏幕：将亮度设为0，关闭自动亮度
                subprocess.run(
                    [self._adb_path, "-s", self._device, "shell",
                     "settings put system screen_brightness_mode 0 && settings put system screen_brightness 0"],
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                self.log_message.emit("[ADB] 屏幕已熄灭（仅电脑端显示）")
            else:
                # 恢复屏幕：恢复亮度
                subprocess.run(
                    [self._adb_path, "-s", self._device, "shell",
                     "settings put system screen_brightness 128 && settings put system screen_brightness_mode 1"],
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                self.log_message.emit("[ADB] 屏幕已恢复")
        except Exception as e:
            self.log_message.emit(f"[ADB] 操作失败: {e}")

    def _on_scrcpy_output(self):
        """读取 scrcpy 输出"""
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        if data.strip():
            lines = data.strip().splitlines()
            self._status_label.setText(f"scrcpy: {lines[-1][:100]}")
            for line in lines:
                self.log_message.emit(f"[scrcpy] {line}")

    def _on_scrcpy_error(self, error):
        """scrcpy 启动错误"""
        error_names = {
            QProcess.FailedToStart: "启动失败(找不到程序或权限不足)",
            QProcess.Crashed: "进程崩溃",
            QProcess.Timedout: "超时",
            QProcess.WriteError: "写入错误",
            QProcess.ReadError: "读取错误",
        }
        err_name = error_names.get(error, f"未知错误({error})")
        self._status_label.setText(f"scrcpy 错误: {err_name}")
        self.log_message.emit(f"[scrcpy] 错误: {err_name}")

    def _on_scrcpy_finished(self, exit_code, exit_status):
        """scrcpy 退出后尝试重启"""
        self._embedded_hwnd = None  # 窗口已销毁
        if self._embed_timer:
            self._embed_timer.stop()
            self._embed_timer = None

        if self._process and self._process.state() == QProcess.NotRunning:
            # 读取剩余输出
            remaining = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace").strip()
            if remaining:
                lines = remaining.splitlines()
                self._status_label.setText(f"scrcpy 退出(code={exit_code}): {lines[-1][:80]}")
                for line in lines:
                    self.log_message.emit(f"[scrcpy] {line}")
            else:
                self._status_label.setText(f"scrcpy 退出(code={exit_code})，3秒后重连...")
            self.log_message.emit(f"[scrcpy] 进程退出 (code={exit_code})，3秒后重连")
            QTimer.singleShot(3000, self._start_scrcpy)

    def _start_fallback(self):
        """降级模式：静态截图"""
        self._container.hide()
        self._fallback_canvas.show()
        self._status_label.setText("scrcpy 不可用，使用静态截图模式")
        # 自动截图
        self._take_screenshot()

    def _take_screenshot(self):
        """ADB 截图并显示"""
        if not self._device:
            return
        try:
            from bot import ADB
            adb = ADB(self._device, self._adb_path)
            if not adb.is_connected():
                adb.connect()
            screenshot_dir = "screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, "current.png")
            if adb.screenshot(path):
                self._last_screenshot = path
                self._fallback_canvas.set_screenshot(path)
        except Exception:
            pass

    def update_screenshot(self, path: str):
        """外部更新截图（Bot 运行时调用）"""
        self._last_screenshot = path
        if self._fallback_canvas.isVisible():
            self._fallback_canvas.set_screenshot(path)

    def stop(self):
        """停止 scrcpy"""
        # 先取消嵌入
        if self._embedded_hwnd and sys.platform == "win32":
            try:
                import ctypes
                # 恢复为顶级窗口
                ctypes.windll.user32.SetParent(self._embedded_hwnd, 0)
            except Exception:
                pass
            self._embedded_hwnd = None

        if self._embed_timer:
            self._embed_timer.stop()
            self._embed_timer = None

        if self._process:
            self._process.finished.disconnect(self._on_scrcpy_finished)
            self._process.terminate()
            if not self._process.waitForFinished(2000):
                self._process.kill()
            self._process = None
        self._status_label.setText("已停止")

    def is_running(self) -> bool:
        return self._process and self._process.state() == QProcess.Running

    def get_last_screenshot(self) -> str | None:
        return self._last_screenshot


# ==================== Bot 线程 ====================

class BotThread(QThread):
    """在子线程中运行 GameBot"""
    log_signal = Signal(str)
    screenshot_signal = Signal(str)
    monitor_signal = Signal(dict)
    status_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, config_path: str, device_override: str = None):
        super().__init__()
        self.config_path = config_path
        self.device_override = device_override
        self._bot = None
        self._stop_flag = False

    def run(self):
        try:
            from bot import GameBot
            self._bot = GameBot(
                self.config_path,
                device_override=self.device_override,
                on_screenshot=self._on_screenshot,
                on_log=self._on_log,
                on_monitor=self._on_monitor,
            )
            self.status_signal.emit("运行中")
            self._bot.run()
        except SystemExit:
            pass
        except Exception as e:
            self.log_signal.emit(f"[ERROR] Bot 异常: {e}")
        finally:
            self.status_signal.emit("已停止")
            self.finished_signal.emit()

    def _on_screenshot(self, path):
        if not self._stop_flag:
            self.screenshot_signal.emit(path)

    def _on_log(self, msg):
        if not self._stop_flag:
            self.log_signal.emit(msg)

    def _on_monitor(self, values):
        if not self._stop_flag:
            self.monitor_signal.emit(values)

    def stop(self):
        self._stop_flag = True
        if self._bot:
            self._bot._stop_requested = True


# ==================== 辅助：截图并弹窗框选 ====================

def take_screenshot_and_pick(device: str, adb_path: str, mode: str, parent=None) -> tuple | None:
    """
    截图并弹出框选/点击对话框。
    mode: "region" 或 "point"
    返回: (x1, y1, x2, y2) 或 (x, y) 或 None（取消）
    """
    try:
        from bot import ADB
        adb = ADB(device, adb_path or "adb")
        if not adb.is_connected():
            if not adb.connect():
                QMessageBox.warning(parent, "连接失败", f"无法连接设备: {device}")
                return None
        screenshot_dir = "screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        path = os.path.join(screenshot_dir, "pick_temp.png")
        if not adb.screenshot(path):
            QMessageBox.warning(parent, "截图失败", "ADB 截图返回失败")
            return None
    except Exception as e:
        QMessageBox.critical(parent, "错误", str(e))
        return None

    dlg = ScreenshotPickDialog(path, mode=mode, parent=parent)
    result = None

    if mode == "region":
        def on_region(x1, y1, x2, y2):
            nonlocal result
            result = (x1, y1, x2, y2)
        dlg.region_picked.connect(on_region)
    else:
        def on_point(x, y):
            nonlocal result
            result = (x, y)
        dlg.point_picked.connect(on_point)

    dlg.exec()
    return result


def crop_template_from_screenshot(screenshot_path: str, x1: int, y1: int,
                                   x2: int, y2: int) -> str | None:
    """从截图中裁剪区域并保存为模板图片"""
    if not screenshot_path or not os.path.exists(screenshot_path):
        return None
    try:
        import cv2
        img = cv2.imdecode(
            np.fromfile(screenshot_path, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if img is None:
            return None
        h, w = img.shape[:2]
        cx1, cy1 = max(0, x1), max(0, y1)
        cx2, cy2 = min(w, x2), min(h, y2)
        cropped = img[cy1:cy2, cx1:cx2]
        if cropped.size == 0:
            return None
        os.makedirs("templates", exist_ok=True)
        ts = time.strftime("%H%M%S")
        filename = f"templates/crop_{ts}_{x1}_{y1}_{x2}_{y2}.png"
        cv2.imencode(".png", cropped)[1].tofile(filename)
        return filename
    except Exception:
        return None


# ==================== 编辑对话框 ====================

class TaskEditDialog(QDialog):
    """任务/步骤编辑对话框"""

    def __init__(self, data: dict, parent=None, is_step=False,
                 device: str = "", adb_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("编辑步骤" if is_step else "编辑任务")
        self.setMinimumWidth(400)
        self.data = dict(data)
        self.is_step = is_step
        self._device = device
        self._adb_path = adb_path

        layout = QFormLayout(self)

        if not is_step:
            self.name_edit = QLineEdit(data.get("name", ""))
            layout.addRow("名称:", self.name_edit)
            self.enabled_cb = QCheckBox("启用")
            self.enabled_cb.setChecked(data.get("enabled", True))
            layout.addRow("", self.enabled_cb)

        self.template_edit = QLineEdit(data.get("template", ""))
        template_btn = QPushButton("浏览...")
        template_btn.clicked.connect(self._browse_template)
        crop_btn = QPushButton("从截图截取")
        crop_btn.setToolTip("截图后在弹窗中框选区域，自动裁剪保存为模板")
        crop_btn.clicked.connect(self._crop_from_screenshot)
        template_row = QHBoxLayout()
        template_row.addWidget(self.template_edit, 1)
        template_row.addWidget(template_btn)
        template_row.addWidget(crop_btn)
        layout.addRow("模板图片:", template_row)

        self.action_combo = QComboBox()
        for label, val in ACTION_LABELS.items():
            self.action_combo.addItem(label, val)
        cur_action = data.get("action", "tap")
        idx = self.action_combo.findData(cur_action)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        layout.addRow("动作类型:", self.action_combo)

        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 9999)
        self.x_spin.setValue(data.get("x", 0))
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 9999)
        self.y_spin.setValue(data.get("y", 0))
        layout.addRow("X 坐标:", self.x_spin)
        layout.addRow("Y 坐标:", self.y_spin)

        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-9999, 9999)
        self.offset_x_spin.setValue(data.get("offset_x", 0))
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-9999, 9999)
        self.offset_y_spin.setValue(data.get("offset_y", 0))
        layout.addRow("X 偏移:", self.offset_x_spin)
        layout.addRow("Y 偏移:", self.offset_y_spin)

        self.keycode_spin = QSpinBox()
        self.keycode_spin.setRange(0, 999)
        self.keycode_spin.setValue(data.get("keycode", 4))
        layout.addRow("按键码:", self.keycode_spin)

        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0, 999)
        self.cooldown_spin.setDecimals(1)
        self.cooldown_spin.setValue(data.get("cooldown", 0.3))
        layout.addRow("冷却(秒):", self.cooldown_spin)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 1.0)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(data.get("threshold", 0.85))
        layout.addRow("阈值:", self.threshold_spin)

        if is_step:
            self.skippable_cb = QCheckBox("识别不到时跳过此步骤")
            self.skippable_cb.setChecked(data.get("skippable", False))
            self.skippable_cb.setToolTip("开启后，如果此步骤的模板在屏幕上找不到，自动跳到下一步")
            layout.addRow("", self.skippable_cb)

        if not is_step:
            self.max_triggers_spin = QSpinBox()
            self.max_triggers_spin.setRange(0, 9999)
            self.max_triggers_spin.setValue(data.get("max_triggers", 0))
            layout.addRow("最大触发(0=无限):", self.max_triggers_spin)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

        self._on_action_changed()

    def _browse_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "templates", "PNG (*.png);;All (*)"
        )
        if path:
            self.template_edit.setText(path)

    def _crop_from_screenshot(self):
        """截图 → 弹窗框选 → 裁剪保存模板"""
        if not self._device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        result = take_screenshot_and_pick(self._device, self._adb_path, "region", self)
        if result:
            x1, y1, x2, y2 = result
            # 裁剪保存
            screenshot_dir = "screenshots"
            temp_path = os.path.join(screenshot_dir, "pick_temp.png")
            template_path = crop_template_from_screenshot(temp_path, x1, y1, x2, y2)
            if template_path:
                self.template_edit.setText(template_path)
                self.statusBar_msg = f"模板已保存: {template_path}"

    def _on_action_changed(self):
        action = self.action_combo.currentData() or "tap"
        is_tap = action == "tap"
        is_tap_coord = action == "tap_coord"
        is_key = action == "key"
        self.x_spin.setEnabled(is_tap_coord)
        self.y_spin.setEnabled(is_tap_coord)
        self.offset_x_spin.setEnabled(is_tap)
        self.offset_y_spin.setEnabled(is_tap)
        self.keycode_spin.setEnabled(is_key)
        self.template_edit.setEnabled(not is_tap_coord)

    def get_data(self) -> dict:
        d = self.data.copy()
        if not self.is_step:
            d["name"] = self.name_edit.text()
            d["enabled"] = self.enabled_cb.isChecked()
        d["template"] = self.template_edit.text()
        d["action"] = self.action_combo.currentData() or "tap"
        d["x"] = self.x_spin.value()
        d["y"] = self.y_spin.value()
        d["offset_x"] = self.offset_x_spin.value()
        d["offset_y"] = self.offset_y_spin.value()
        d["keycode"] = self.keycode_spin.value()
        d["cooldown"] = self.cooldown_spin.value()
        d["threshold"] = self.threshold_spin.value()
        if self.is_step:
            d["skippable"] = self.skippable_cb.isChecked()
        if not self.is_step:
            d["max_triggers"] = self.max_triggers_spin.value()
        return d


class ChainEditDialog(QDialog):
    """链编辑对话框"""

    def __init__(self, data: dict, monitor_names: list, parent=None,
                 device: str = "", adb_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("编辑步骤链")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.data = dict(data)
        self.monitor_names = monitor_names
        self._device = device
        self._adb_path = adb_path

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(data.get("name", ""))
        form.addRow("名称:", self.name_edit)
        self.enabled_cb = QCheckBox("启用")
        self.enabled_cb.setChecked(data.get("enabled", True))
        form.addRow("", self.enabled_cb)
        self.reset_timeout_spin = QSpinBox()
        self.reset_timeout_spin.setRange(1, 9999)
        self.reset_timeout_spin.setValue(data.get("reset_timeout", 30))
        form.addRow("重置超时(秒):", self.reset_timeout_spin)

        self.close_template_edit = QLineEdit(data.get("close_template", ""))
        close_btn = QPushButton("浏览...")
        close_btn.clicked.connect(lambda: self._browse(self.close_template_edit))
        close_crop_btn = QPushButton("从截图截取")
        close_crop_btn.clicked.connect(lambda: self._crop_for_field(self.close_template_edit))
        close_row = QHBoxLayout()
        close_row.addWidget(self.close_template_edit, 1)
        close_row.addWidget(close_btn)
        close_row.addWidget(close_crop_btn)
        form.addRow("关闭模板:", close_row)
        layout.addLayout(form)

        # 跳过条件
        skip_group = QGroupBox("跳过条件")
        skip_layout = QVBoxLayout(skip_group)
        self.skip_list = QListWidget()
        for cond in data.get("skip_conditions", []):
            self.skip_list.addItem(
                f"{cond.get('monitor','')} {cond.get('field','value')} "
                f"{cond.get('op','<')} {cond.get('value',0)}"
            )
        skip_layout.addWidget(self.skip_list)
        skip_btn_row = QHBoxLayout()
        add_skip_btn = QPushButton("添加条件")
        add_skip_btn.clicked.connect(self._add_skip_condition)
        del_skip_btn = QPushButton("删除")
        del_skip_btn.clicked.connect(self._del_skip_condition)
        skip_btn_row.addWidget(add_skip_btn)
        skip_btn_row.addWidget(del_skip_btn)
        skip_layout.addLayout(skip_btn_row)
        layout.addWidget(skip_group)

        # 步骤列表
        steps_group = QGroupBox("步骤列表")
        steps_layout = QVBoxLayout(steps_group)
        self.steps_list = QListWidget()
        self._steps_data = list(data.get("steps", []))
        self._refresh_steps_list()
        steps_layout.addWidget(self.steps_list)
        steps_btn_row = QHBoxLayout()
        add_step_btn = QPushButton("添加步骤")
        add_step_btn.clicked.connect(self._add_step)
        edit_step_btn = QPushButton("编辑")
        edit_step_btn.clicked.connect(self._edit_step)
        del_step_btn = QPushButton("删除")
        del_step_btn.clicked.connect(self._del_step)
        up_step_btn = QPushButton("上移")
        up_step_btn.clicked.connect(lambda: self._move_step(-1))
        down_step_btn = QPushButton("下移")
        down_step_btn.clicked.connect(lambda: self._move_step(1))
        steps_btn_row.addWidget(add_step_btn)
        steps_btn_row.addWidget(edit_step_btn)
        steps_btn_row.addWidget(del_step_btn)
        steps_btn_row.addWidget(up_step_btn)
        steps_btn_row.addWidget(down_step_btn)
        steps_layout.addLayout(steps_btn_row)
        layout.addWidget(steps_group)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _browse(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "templates", "PNG (*.png);;All (*)"
        )
        if path:
            edit.setText(path)

    def _crop_for_field(self, edit: QLineEdit):
        """截图 → 弹窗框选 → 裁剪保存 → 填入指定编辑框"""
        if not self._device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        result = take_screenshot_and_pick(self._device, self._adb_path, "region", self)
        if result:
            x1, y1, x2, y2 = result
            screenshot_dir = "screenshots"
            temp_path = os.path.join(screenshot_dir, "pick_temp.png")
            template_path = crop_template_from_screenshot(temp_path, x1, y1, x2, y2)
            if template_path:
                edit.setText(template_path)

    def _refresh_steps_list(self):
        self.steps_list.clear()
        for i, step in enumerate(self._steps_data):
            tpl = step.get("template", "")
            action = step.get("action", "tap")
            action_label = ACTION_VALUES.get(action, action)
            skip_mark = " [可跳过]" if step.get("skippable", False) else ""
            if action == "tap_coord":
                label = f"步骤{i+1}: 点击坐标({step.get('x',0)},{step.get('y',0)}){skip_mark}"
            else:
                label = f"步骤{i+1}: {os.path.basename(tpl)} [{action_label}]{skip_mark}"
            self.steps_list.addItem(label)

    def _add_step(self):
        step = {"action": "tap", "cooldown": 0.3, "threshold": 0.85}
        dlg = TaskEditDialog(step, self, is_step=True,
                             device=self._device, adb_path=self._adb_path)
        if dlg.exec() == QDialog.Accepted:
            self._steps_data.append(dlg.get_data())
            self._refresh_steps_list()

    def _edit_step(self):
        idx = self.steps_list.currentRow()
        if idx < 0:
            return
        dlg = TaskEditDialog(self._steps_data[idx], self, is_step=True,
                             device=self._device, adb_path=self._adb_path)
        if dlg.exec() == QDialog.Accepted:
            self._steps_data[idx] = dlg.get_data()
            self._refresh_steps_list()

    def _del_step(self):
        idx = self.steps_list.currentRow()
        if idx >= 0:
            self._steps_data.pop(idx)
            self._refresh_steps_list()

    def _move_step(self, delta):
        idx = self.steps_list.currentRow()
        new_idx = idx + delta
        if 0 <= idx < len(self._steps_data) and 0 <= new_idx < len(self._steps_data):
            self._steps_data[idx], self._steps_data[new_idx] = \
                self._steps_data[new_idx], self._steps_data[idx]
            self._refresh_steps_list()
            self.steps_list.setCurrentRow(new_idx)

    def _add_skip_condition(self):
        if not self.monitor_names:
            QMessageBox.warning(self, "提示", "请先添加监控项")
            return
        name, ok = QInputDialog.getItem(
            self, "添加跳过条件", "选择监控项:", self.monitor_names, 0, False
        )
        if not ok:
            return
        field, ok = QInputDialog.getItem(
            self, "字段", "选择字段:", ["value", "current", "total"], 0, False
        )
        if not ok:
            return
        op, ok = QInputDialog.getItem(
            self, "运算符", "选择运算符:", ["<", "<=", ">", ">="], 0, False
        )
        if not ok:
            return
        val, ok = QInputDialog.getInt(self, "阈值", "输入阈值:", 0)
        if not ok:
            return
        self.skip_list.addItem(f"{name} {field} {op} {val}")

    def _del_skip_condition(self):
        idx = self.skip_list.currentRow()
        if idx >= 0:
            self.skip_list.takeItem(idx)

    def get_data(self) -> dict:
        d = self.data.copy()
        d["name"] = self.name_edit.text()
        d["enabled"] = self.enabled_cb.isChecked()
        d["reset_timeout"] = self.reset_timeout_spin.value()
        d["close_template"] = self.close_template_edit.text()
        d["steps"] = self._steps_data
        skip_conds = []
        for i in range(self.skip_list.count()):
            parts = self.skip_list.item(i).text().split()
            if len(parts) >= 4:
                skip_conds.append({
                    "monitor": parts[0], "field": parts[1],
                    "op": parts[2], "value": int(parts[3]),
                })
        d["skip_conditions"] = skip_conds
        return d


class MonitorEditDialog(QDialog):
    """监控项编辑对话框"""

    def __init__(self, data: dict, parent=None,
                 device: str = "", adb_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("编辑监控项")
        self.setMinimumWidth(450)
        self.data = dict(data)
        self._device = device
        self._adb_path = adb_path

        layout = QFormLayout(self)

        self.name_edit = QLineEdit(data.get("name", ""))
        layout.addRow("名称:", self.name_edit)

        self.enabled_cb = QCheckBox("启用")
        self.enabled_cb.setChecked(data.get("enabled", True))
        layout.addRow("", self.enabled_cb)

        # region
        region = data.get("region", [0, 0, 0, 0])
        self.region_edits = []
        region_row = QHBoxLayout()
        for i, label in enumerate(["X1", "Y1", "X2", "Y2"]):
            region_row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(region[i] if i < len(region) else 0)
            self.region_edits.append(spin)
            region_row.addWidget(spin)
        region_pick_btn = QPushButton("从截图框选")
        region_pick_btn.setToolTip("截图后在弹窗中框选区域")
        region_pick_btn.clicked.connect(self._pick_region)
        region_row.addWidget(region_pick_btn)
        layout.addRow("区域:", region_row)

        # 前置操作
        pre_type_row = QHBoxLayout()
        self.pre_type_combo = QComboBox()
        self.pre_type_combo.addItem("无", "none")
        self.pre_type_combo.addItem("点击位置", "tap")
        self.pre_type_combo.addItem("区域匹配", "template")
        pre_type = data.get("pre_type", "tap" if data.get("pre_tap", [0, 0]) != [0, 0] else
                              "template" if data.get("pre_template", "") else "none")
        idx = self.pre_type_combo.findData(pre_type)
        if idx >= 0:
            self.pre_type_combo.setCurrentIndex(idx)
        self.pre_type_combo.currentIndexChanged.connect(self._on_pre_type_changed)
        pre_type_row.addWidget(self.pre_type_combo)

        # 前置点击坐标
        pre_tap = data.get("pre_tap", [0, 0])
        self.pretap_x = QSpinBox()
        self.pretap_x.setRange(0, 9999)
        self.pretap_x.setValue(pre_tap[0] if len(pre_tap) > 0 else 0)
        self.pretap_y = QSpinBox()
        self.pretap_y.setRange(0, 9999)
        self.pretap_y.setValue(pre_tap[1] if len(pre_tap) > 1 else 0)
        pretap_pick_btn = QPushButton("从截图选取")
        pretap_pick_btn.setToolTip("截图后在弹窗中点击选取坐标")
        pretap_pick_btn.clicked.connect(self._pick_pretap)

        self.pretap_widget = QWidget()
        pretap_layout = QHBoxLayout(self.pretap_widget)
        pretap_layout.setContentsMargins(0, 0, 0, 0)
        pretap_layout.addWidget(QLabel("X:"))
        pretap_layout.addWidget(self.pretap_x)
        pretap_layout.addWidget(QLabel("Y:"))
        pretap_layout.addWidget(self.pretap_y)
        pretap_layout.addWidget(pretap_pick_btn)

        # 前置区域匹配
        self.pre_template_edit = QLineEdit(data.get("pre_template", ""))
        pre_tmpl_browse_btn = QPushButton("浏览...")
        pre_tmpl_browse_btn.clicked.connect(lambda: self._browse(self.pre_template_edit))
        pre_tmpl_crop_btn = QPushButton("从截图截取")
        pre_tmpl_crop_btn.clicked.connect(lambda: self._crop_for_field(self.pre_template_edit))

        self.pre_skippable_cb = QCheckBox("识别不到时跳过")
        self.pre_skippable_cb.setChecked(data.get("pre_skippable", True))
        self.pre_skippable_cb.setToolTip("开启后，如果前置模板在屏幕上找不到，跳过本次监控")

        self.pretemplate_widget = QWidget()
        pretemplate_layout = QVBoxLayout(self.pretemplate_widget)
        pretemplate_layout.setContentsMargins(0, 0, 0, 0)
        tmpl_row = QHBoxLayout()
        tmpl_row.addWidget(self.pre_template_edit, 1)
        tmpl_row.addWidget(pre_tmpl_browse_btn)
        tmpl_row.addWidget(pre_tmpl_crop_btn)
        pretemplate_layout.addLayout(tmpl_row)
        pretemplate_layout.addWidget(self.pre_skippable_cb)

        pre_group = QGroupBox("前置操作")
        pre_layout = QVBoxLayout(pre_group)
        pre_layout.addWidget(self.pre_type_combo)
        pre_layout.addWidget(self.pretap_widget)
        pre_layout.addWidget(self.pretemplate_widget)
        layout.addRow(pre_group)

        self._on_pre_type_changed()

        self.fixed_total_spin = QSpinBox()
        self.fixed_total_spin.setRange(0, 99999)
        self.fixed_total_spin.setValue(data.get("fixed_total", 0))
        self.fixed_total_spin.setSpecialValueText("自动(0)")
        layout.addRow("固定总值:", self.fixed_total_spin)

        self.report_combo = QComboBox()
        for label, val in REPORT_LABELS.items():
            self.report_combo.addItem(label, val)
        cur_report = data.get("report", "current")
        idx = self.report_combo.findData(cur_report)
        if idx >= 0:
            self.report_combo.setCurrentIndex(idx)
        layout.addRow("报告类型:", self.report_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 9999)
        self.interval_spin.setValue(data.get("interval", 60))
        layout.addRow("间隔(秒):", self.interval_spin)

        self.alert_spin = QSpinBox()
        self.alert_spin.setRange(0, 99999)
        self.alert_spin.setValue(data.get("alert_threshold", 0))
        self.alert_spin.setSpecialValueText("关闭(0)")
        layout.addRow("提醒阈值:", self.alert_spin)

        self.close_template_edit = QLineEdit(data.get("close_template", ""))
        close_btn = QPushButton("浏览...")
        close_btn.clicked.connect(lambda: self._browse(self.close_template_edit))
        close_crop_btn = QPushButton("从截图截取")
        close_crop_btn.clicked.connect(lambda: self._crop_for_field(self.close_template_edit))
        close_row = QHBoxLayout()
        close_row.addWidget(self.close_template_edit, 1)
        close_row.addWidget(close_btn)
        close_row.addWidget(close_crop_btn)
        layout.addRow("关闭模板:", close_row)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def _browse(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "templates", "PNG (*.png);;All (*)"
        )
        if path:
            edit.setText(path)

    def _crop_for_field(self, edit: QLineEdit):
        """截图 → 弹窗框选 → 裁剪保存 → 填入指定编辑框"""
        if not self._device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        result = take_screenshot_and_pick(self._device, self._adb_path, "region", self)
        if result:
            x1, y1, x2, y2 = result
            screenshot_dir = "screenshots"
            temp_path = os.path.join(screenshot_dir, "pick_temp.png")
            template_path = crop_template_from_screenshot(temp_path, x1, y1, x2, y2)
            if template_path:
                edit.setText(template_path)

    def _pick_region(self):
        """截图 → 弹窗框选 → 填入 region"""
        if not self._device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        result = take_screenshot_and_pick(self._device, self._adb_path, "region", self)
        if result:
            x1, y1, x2, y2 = result
            self.region_edits[0].setValue(x1)
            self.region_edits[1].setValue(y1)
            self.region_edits[2].setValue(x2)
            self.region_edits[3].setValue(y2)

    def _pick_pretap(self):
        """截图 → 弹窗点击 → 填入 pre_tap"""
        if not self._device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        result = take_screenshot_and_pick(self._device, self._adb_path, "point", self)
        if result:
            x, y = result
            self.pretap_x.setValue(x)
            self.pretap_y.setValue(y)

    def _on_pre_type_changed(self):
        pre_type = self.pre_type_combo.currentData()
        self.pretap_widget.setVisible(pre_type == "tap")
        self.pretemplate_widget.setVisible(pre_type == "template")

    def get_data(self) -> dict:
        d = self.data.copy()
        d["name"] = self.name_edit.text()
        d["enabled"] = self.enabled_cb.isChecked()
        d["region"] = [s.value() for s in self.region_edits]
        pre_type = self.pre_type_combo.currentData()
        d["pre_type"] = pre_type
        if pre_type == "tap":
            d["pre_tap"] = [self.pretap_x.value(), self.pretap_y.value()]
            d.pop("pre_template", None)
            d.pop("pre_skippable", None)
        elif pre_type == "template":
            d["pre_template"] = self.pre_template_edit.text()
            d["pre_skippable"] = self.pre_skippable_cb.isChecked()
            d.pop("pre_tap", None)
        else:
            d.pop("pre_tap", None)
            d.pop("pre_template", None)
            d.pop("pre_skippable", None)
        d["fixed_total"] = self.fixed_total_spin.value()
        d["report"] = self.report_combo.currentData() or "current"
        d["interval"] = self.interval_spin.value()
        d["alert_threshold"] = self.alert_spin.value()
        d["close_template"] = self.close_template_edit.text()
        return d


# ==================== 配置面板 ====================

class ConfigPanel(QWidget):
    """左侧配置面板"""

    config_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = {}
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(8)

        # 设备设置
        device_group = QGroupBox("设备设置")
        device_form = QFormLayout()
        self.device_edit = QLineEdit()
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 60)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setSingleStep(0.1)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 1.0)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.05)
        self.adb_path_edit = QLineEdit()
        self.screenshot_dir_edit = QLineEdit()
        device_form.addRow("设备地址:", self.device_edit)
        device_form.addRow("间隔(秒):", self.interval_spin)
        device_form.addRow("匹配阈值:", self.threshold_spin)
        device_form.addRow("ADB路径:", self.adb_path_edit)
        device_form.addRow("截图目录:", self.screenshot_dir_edit)
        device_group.setLayout(device_form)
        layout.addWidget(device_group)

        # 任务列表
        tasks_group = QGroupBox("独立任务")
        tasks_layout = QVBoxLayout()
        self.tasks_list = QListWidget()
        self.tasks_list.setMaximumHeight(120)
        tasks_layout.addWidget(self.tasks_list)
        tasks_btn_row = QHBoxLayout()
        add_task_btn = QPushButton("+ 添加")
        add_task_btn.clicked.connect(self._add_task)
        edit_task_btn = QPushButton("编辑")
        edit_task_btn.clicked.connect(self._edit_task)
        del_task_btn = QPushButton("删除")
        del_task_btn.clicked.connect(self._del_task)
        tasks_btn_row.addWidget(add_task_btn)
        tasks_btn_row.addWidget(edit_task_btn)
        tasks_btn_row.addWidget(del_task_btn)
        tasks_layout.addLayout(tasks_btn_row)
        tasks_group.setLayout(tasks_layout)
        layout.addWidget(tasks_group)

        # 步骤链
        chains_group = QGroupBox("步骤链")
        chains_layout = QVBoxLayout()
        self.chains_list = QListWidget()
        self.chains_list.setMaximumHeight(120)
        chains_layout.addWidget(self.chains_list)
        chains_btn_row = QHBoxLayout()
        add_chain_btn = QPushButton("+ 添加")
        add_chain_btn.clicked.connect(self._add_chain)
        edit_chain_btn = QPushButton("编辑")
        edit_chain_btn.clicked.connect(self._edit_chain)
        del_chain_btn = QPushButton("删除")
        del_chain_btn.clicked.connect(self._del_chain)
        chains_btn_row.addWidget(add_chain_btn)
        chains_btn_row.addWidget(edit_chain_btn)
        chains_btn_row.addWidget(del_chain_btn)
        chains_layout.addLayout(chains_btn_row)
        chains_group.setLayout(chains_layout)
        layout.addWidget(chains_group)

        # 监控项
        monitors_group = QGroupBox("监控项")
        monitors_layout = QVBoxLayout()
        self.monitors_list = QListWidget()
        self.monitors_list.setMaximumHeight(120)
        monitors_layout.addWidget(self.monitors_list)
        monitors_btn_row = QHBoxLayout()
        add_monitor_btn = QPushButton("+ 添加")
        add_monitor_btn.clicked.connect(self._add_monitor)
        edit_monitor_btn = QPushButton("编辑")
        edit_monitor_btn.clicked.connect(self._edit_monitor)
        del_monitor_btn = QPushButton("删除")
        del_monitor_btn.clicked.connect(self._del_monitor)
        monitors_btn_row.addWidget(add_monitor_btn)
        monitors_btn_row.addWidget(edit_monitor_btn)
        monitors_btn_row.addWidget(del_monitor_btn)
        monitors_layout.addLayout(monitors_btn_row)
        monitors_group.setLayout(monitors_layout)
        layout.addWidget(monitors_group)

        # 日志
        log_group = QGroupBox("日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        self.log_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; background: #1e1e1e; color: #d4d4d4;"
        )
        log_layout.addWidget(self.log_text)
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_log_btn)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        layout.addStretch()
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _get_device_info(self):
        return self.device_edit.text(), self.adb_path_edit.text()

    def load_config(self, config: dict):
        self._config = config
        self.device_edit.setText(config.get("device", ""))
        self.interval_spin.setValue(config.get("interval", 1.0))
        self.threshold_spin.setValue(config.get("threshold", 0.85))
        self.adb_path_edit.setText(config.get("adb_path", "adb"))
        self.screenshot_dir_edit.setText(config.get("screenshot_dir", "screenshots"))

        self.tasks_list.clear()
        for t in config.get("tasks", []):
            enabled = "✅" if t.get("enabled", True) else "❌"
            self.tasks_list.addItem(f"{enabled} {t.get('name', '')}")

        self.chains_list.clear()
        for c in config.get("chains", []):
            enabled = "✅" if c.get("enabled", True) else "❌"
            steps = len(c.get("steps", []))
            self.chains_list.addItem(f"{enabled} {c.get('name', '')} ({steps}步)")

        self.monitors_list.clear()
        for m in config.get("monitors", []):
            enabled = "✅" if m.get("enabled", True) else "❌"
            self.monitors_list.addItem(f"{enabled} {m.get('name', '')}")

    def get_config(self) -> dict:
        config = dict(self._config)
        config["device"] = self.device_edit.text()
        config["interval"] = self.interval_spin.value()
        config["threshold"] = self.threshold_spin.value()
        config["adb_path"] = self.adb_path_edit.text()
        config["screenshot_dir"] = self.screenshot_dir_edit.text()
        return config

    def append_log(self, msg: str):
        self.log_text.append(msg)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ---- 任务 ----
    def _add_task(self):
        device, adb_path = self._get_device_info()
        task = {"name": "新任务", "enabled": True, "template": "", "action": "tap",
                "offset_x": 0, "offset_y": 0, "cooldown": 0.3, "max_triggers": 0}
        dlg = TaskEditDialog(task, self, device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self._config.setdefault("tasks", []).append(data)
            enabled = "✅" if data.get("enabled", True) else "❌"
            self.tasks_list.addItem(f"{enabled} {data.get('name', '')}")
            self.config_changed.emit()

    def _edit_task(self):
        idx = self.tasks_list.currentRow()
        if idx < 0:
            return
        device, adb_path = self._get_device_info()
        dlg = TaskEditDialog(self._config["tasks"][idx], self, device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            self._config["tasks"][idx] = dlg.get_data()
            data = dlg.get_data()
            enabled = "✅" if data.get("enabled", True) else "❌"
            self.tasks_list.item(idx).setText(f"{enabled} {data.get('name', '')}")
            self.config_changed.emit()

    def _del_task(self):
        idx = self.tasks_list.currentRow()
        if idx >= 0:
            self._config["tasks"].pop(idx)
            self.tasks_list.takeItem(idx)
            self.config_changed.emit()

    # ---- 链 ----
    def _get_monitor_names(self):
        return [m.get("name", "") for m in self._config.get("monitors", [])]

    def _add_chain(self):
        device, adb_path = self._get_device_info()
        chain = {"name": "新链", "enabled": True, "reset_timeout": 30, "steps": []}
        dlg = ChainEditDialog(chain, self._get_monitor_names(), self,
                              device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self._config.setdefault("chains", []).append(data)
            enabled = "✅" if data.get("enabled", True) else "❌"
            steps = len(data.get("steps", []))
            self.chains_list.addItem(f"{enabled} {data.get('name', '')} ({steps}步)")
            self.config_changed.emit()

    def _edit_chain(self):
        idx = self.chains_list.currentRow()
        if idx < 0:
            return
        device, adb_path = self._get_device_info()
        dlg = ChainEditDialog(self._config["chains"][idx], self._get_monitor_names(), self,
                              device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            self._config["chains"][idx] = dlg.get_data()
            data = dlg.get_data()
            enabled = "✅" if data.get("enabled", True) else "❌"
            steps = len(data.get("steps", []))
            self.chains_list.item(idx).setText(f"{enabled} {data.get('name', '')} ({steps}步)")
            self.config_changed.emit()

    def _del_chain(self):
        idx = self.chains_list.currentRow()
        if idx >= 0:
            self._config["chains"].pop(idx)
            self.chains_list.takeItem(idx)
            self.config_changed.emit()

    # ---- 监控 ----
    def _add_monitor(self):
        device, adb_path = self._get_device_info()
        monitor = {"name": "新监控", "enabled": True, "region": [0, 0, 0, 0],
                   "report": "current", "interval": 60, "alert_threshold": 0}
        dlg = MonitorEditDialog(monitor, self, device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self._config.setdefault("monitors", []).append(data)
            enabled = "✅" if data.get("enabled", True) else "❌"
            self.monitors_list.addItem(f"{enabled} {data.get('name', '')}")
            self.config_changed.emit()

    def _edit_monitor(self):
        idx = self.monitors_list.currentRow()
        if idx < 0:
            return
        device, adb_path = self._get_device_info()
        dlg = MonitorEditDialog(self._config["monitors"][idx], self,
                                device=device, adb_path=adb_path)
        if dlg.exec() == QDialog.Accepted:
            self._config["monitors"][idx] = dlg.get_data()
            data = dlg.get_data()
            enabled = "✅" if data.get("enabled", True) else "❌"
            self.monitors_list.item(idx).setText(f"{enabled} {data.get('name', '')}")
            self.config_changed.emit()

    def _del_monitor(self):
        idx = self.monitors_list.currentRow()
        if idx >= 0:
            self._config["monitors"].pop(idx)
            self.monitors_list.takeItem(idx)
            self.config_changed.emit()


# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("无尽冬日 - 自动化")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "图标.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            # 默认图标：蓝色圆形带字母 B
            pixmap = QPixmap(64, 64)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#4a90d9"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(4, 4, 56, 56)
            painter.setPen(QColor("white"))
            font = painter.font()
            font.setPixelSize(40)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "B")
            painter.end()
            self.setWindowIcon(QIcon(pixmap))
        self.setMinimumSize(1100, 750)
        self.resize(1280, 800)

        self._config_path = "config.yaml"
        self._config = {}
        self._bot_thread = None

        self._init_ui()
        self._init_menu()
        self._load_config()

        # 首次启动自动运行 Bot
        QTimer.singleShot(500, self._start_bot)

    def _init_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # 左侧配置面板
        self.config_panel = ConfigPanel()
        self.config_panel.setMinimumWidth(340)
        self.config_panel.setMaximumWidth(500)
        self.config_panel.config_changed.connect(self._save_config)
        splitter.addWidget(self.config_panel)

        # 右侧：scrcpy/截图
        self.scrcpy_widget = ScrcpyWidget()
        self.scrcpy_widget.log_message.connect(self.config_panel.append_log)
        splitter.addWidget(self.scrcpy_widget)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 900])

        self.setCentralWidget(splitter)

        # 状态栏永久 widget：体力、队列
        self._stamina_label = QLabel("体力: --")
        self._queue_label = QLabel("剩余队列: --")
        for lbl in (self._stamina_label, self._queue_label):
            lbl.setStyleSheet("padding: 0 8px;")
            self.statusBar().addPermanentWidget(lbl)
        self.statusBar().showMessage("就绪")

    def _init_menu(self):
        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu("文件")
        save_action = QAction("保存配置", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_config)
        file_menu.addAction(save_action)
        reload_action = QAction("重新加载配置", self)
        reload_action.triggered.connect(self._load_config)
        file_menu.addAction(reload_action)

        # 操作
        action_menu = menubar.addMenu("操作")

        self.start_action = QAction("启动 Bot", self)
        self.start_action.triggered.connect(self._start_bot)
        action_menu.addAction(self.start_action)

        self.stop_action = QAction("停止 Bot", self)
        self.stop_action.triggered.connect(self._stop_bot)
        self.stop_action.setEnabled(False)
        action_menu.addAction(self.stop_action)

        action_menu.addSeparator()

        self.scrcpy_start_action = QAction("启动画面", self)
        self.scrcpy_start_action.triggered.connect(self._start_scrcpy)
        action_menu.addAction(self.scrcpy_start_action)

        self.scrcpy_stop_action = QAction("停止画面", self)
        self.scrcpy_stop_action.triggered.connect(self._stop_scrcpy)
        self.scrcpy_stop_action.setEnabled(False)
        action_menu.addAction(self.scrcpy_stop_action)

        action_menu.addSeparator()

        screenshot_action = QAction("手动截图", self)
        screenshot_action.triggered.connect(self._manual_screenshot)
        action_menu.addAction(screenshot_action)

    # ---- 配置 ----
    def _load_config(self):
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._config = {}
            self.config_panel.append_log("[WARNING] 配置文件不存在，使用默认值")
        self.config_panel.load_config(self._config)

    def _save_config(self):
        config = self.config_panel.get_config()
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            self.config_panel.append_log("[INFO] 配置已保存")
            self.statusBar().showMessage("配置已保存", 3000)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ---- Bot ----
    def _start_bot(self):
        if self._bot_thread and self._bot_thread.isRunning():
            return
        self._save_config()

        self._bot_thread = BotThread(self._config_path)
        self._bot_thread.log_signal.connect(self.config_panel.append_log)
        self._bot_thread.screenshot_signal.connect(self._on_screenshot_update)
        self._bot_thread.monitor_signal.connect(self._on_monitor_update)
        self._bot_thread.status_signal.connect(self._on_bot_status)
        self._bot_thread.finished_signal.connect(self._on_bot_finished)
        self._bot_thread._stop_flag = False

        self._bot_thread.start()
        self.start_action.setEnabled(False)
        self.stop_action.setEnabled(True)

        # 同时启动 scrcpy
        self._start_scrcpy()

    def _stop_bot(self):
        if self._bot_thread and self._bot_thread.isRunning():
            self._bot_thread.stop()
            self._bot_thread.wait(3000)
            if self._bot_thread.isRunning():
                self._bot_thread.terminate()
            self._on_bot_finished()

    def _on_bot_status(self, status):
        self.statusBar().showMessage(f"Bot: {status}")

    def _on_bot_finished(self):
        self.start_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.statusBar().showMessage("Bot 已停止")

    def _on_screenshot_update(self, path):
        self.scrcpy_widget.update_screenshot(path)

    def _on_monitor_update(self, values):
        """更新状态栏监控数据（体力、队列等）"""
        for name, data in values.items():
            current = data.get("current", "?")
            total = data.get("total", "?")
            value = data.get("value", "?")
            if "体力" in name:
                self._stamina_label.setText(f"体力: {current}/{total}")
            elif "队列" in name:
                self._queue_label.setText(f"剩余队列: {value}")

    # ---- Scrcpy ----
    def _start_scrcpy(self):
        device = self.config_panel.device_edit.text()
        if not device:
            return
        scrcpy_cfg = self._config.get("scrcpy", {})
        self.scrcpy_widget.start(
            device=device,
            adb_path=self.config_panel.adb_path_edit.text() or "adb",
            scrcpy_path=scrcpy_cfg.get("path", "scrcpy"),
            max_size=scrcpy_cfg.get("max_size", 800),
        )
        self.scrcpy_start_action.setEnabled(False)
        self.scrcpy_stop_action.setEnabled(True)

    def _stop_scrcpy(self):
        self.scrcpy_widget.stop()
        self.scrcpy_start_action.setEnabled(True)
        self.scrcpy_stop_action.setEnabled(False)

    # ---- 手动截图 ----
    def _manual_screenshot(self):
        device = self.config_panel.device_edit.text()
        if not device:
            QMessageBox.warning(self, "提示", "请先设置设备地址")
            return
        try:
            from bot import ADB
            adb = ADB(device, self.config_panel.adb_path_edit.text() or "adb")
            if not adb.is_connected():
                if not adb.connect():
                    QMessageBox.critical(self, "连接失败", f"无法连接设备: {device}")
                    return
            screenshot_dir = self.config_panel.screenshot_dir_edit.text() or "screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, "current.png")
            if adb.screenshot(path):
                self.scrcpy_widget.update_screenshot(path)
                self.statusBar().showMessage("截图成功", 3000)
            else:
                QMessageBox.critical(self, "截图失败", "ADB 截图返回失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def closeEvent(self, event):
        if self._bot_thread and self._bot_thread.isRunning():
            self._bot_thread.stop()
            self._bot_thread.wait(3000)
            if self._bot_thread.isRunning():
                self._bot_thread.terminate()
        self.scrcpy_widget.stop()
        event.accept()


# ==================== 入口 ====================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 暗色主题
    palette = app.palette()
    from PySide6.QtGui import QPalette
    palette.setColor(QPalette.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.Button, QColor(55, 55, 58))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.BrightText, QColor(255, 50, 50))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

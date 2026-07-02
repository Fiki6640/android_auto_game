#!/usr/bin/env python3
"""
Android Auto Game
================
WiFi ADB + OpenCV 截图匹配 + 自动点击
用法: python bot.py [--config config.yaml] [--device 192.168.x.x:5555]
"""

import subprocess
import time
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

try:
    import cv2
    import numpy as np
    import yaml
except ImportError:
    print("[!] 缺少依赖，正在安装...")
    subprocess.check_call(["uv", "sync"])
    import cv2
    import numpy as np
    import yaml

# ==================== 提示音 ====================
try:
    import winsound
    def beep():
        """播放完成提示音"""
        # 800hz频率，200ms时长
        # winsound.Beep(800, 200)
except ImportError:
    def beep():
        print("\a", end="", flush=True)

# ==================== 日志设置 ====================
class ReverseFileHandler(logging.FileHandler):
    """日志文件处理器：最新记录放在文件最前面"""
    def emit(self, record):
        msg = self.format(record) + "\n"
        try:
            if os.path.exists(self.baseFilename):
                with open(self.baseFilename, "r", encoding="utf-8") as f:
                    old = f.read()
            else:
                old = ""
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.write(msg + old)
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        ReverseFileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("AndroidBot")


class CallbackLogHandler(logging.Handler):
    """将日志转发到回调函数（供 GUI 使用）"""
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        if self.callback:
            msg = self.format(record)
            try:
                self.callback(msg)
            except Exception:
                pass


def _run_subprocess(cmd, timeout=15):
    """运行子进程，超时后自动杀进程，返回 (returncode, stdout, stderr)"""
    process = None
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        log.warning(f"子进程超时 ({timeout}s): {' '.join(cmd)}")
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass
        return -1, b"", b"timeout"
    except Exception as e:
        log.error(f"子进程异常: {e}")
        if process is not None:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass
        return -1, b"", b"error"


# ==================== ADB 工具类 ====================
class ADB:
    def __init__(self, device: str, adb_path: str = "adb"):
        self.device = device
        self.adb = adb_path or "adb"
        self._exec_out_ok = None  # None=未知, True=可用, False=不可用
        self._exec_out_attempts = 0

    def _run(self, *args, timeout=15):
        cmd = [self.adb, "-s", self.device] + list(args)
        rc, out, err = _run_subprocess(cmd, timeout=timeout)
        return rc == 0, out, err

    def connect(self) -> bool:
        log.info(f"正在连接设备: {self.device}")
        rc, out, err = _run_subprocess([self.adb, "connect", self.device], timeout=10)
        out_text = out.decode(errors="ignore")
        connected = rc == 0 and ("connected" in out_text or "already connected" in out_text)
        if connected:
            log.info(f"✅ 已连接: {self.device}")
        else:
            err_text = err.decode(errors="ignore")[:200]
            log.error(f"❌ 连接失败: {out_text[:200]} {err_text}")
        return connected

    def is_connected(self) -> bool:
        rc, out, _ = _run_subprocess([self.adb, "devices"], timeout=5)
        if rc != 0:
            return False
        out_text = out.decode(errors="ignore")
        return self.device in out_text

    def _screenshot_fallback(self, save_path: str) -> bool:
        """回退路径：先保存到设备 /sdcard，再 pull"""
        remote_path = "/sdcard/android_bot_screenshot.png"
        rc, _, err2 = _run_subprocess(
            [self.adb, "-s", self.device, "shell", "screencap", "-p", remote_path],
            timeout=10,
        )
        if rc != 0:
            err_text = (err2.decode(errors="ignore")[:100]) if err2 else "screencap 失败"
            log.warning(f"截图回退路径失败: {err_text}")
            return False
        rc2, _, err3 = _run_subprocess(
            [self.adb, "-s", self.device, "pull", remote_path, save_path],
            timeout=10,
        )
        if rc2 == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
            return True
        err_text = (err3.decode(errors="ignore")[:100]) if err3 else "pull 失败"
        log.warning(f"截图回退路径 pull 失败: {err_text}")
        return False

    def screenshot(self, save_path: str) -> bool:
        """截图并保存到本地；exec-out 失败时回退到设备存储再 pull"""
        # 如果已知 exec-out 不可用，直接走回退路径，避免每次等待 5s 超时
        # 每 10 次仍会重试一次 exec-out，防止设备状态恢复后仍用慢路径
        try_exec_out = self._exec_out_ok is not False or self._exec_out_attempts % 10 == 0
        self._exec_out_attempts += 1

        if try_exec_out:
            ok, out, err = self._run("exec-out", "screencap", "-p", timeout=5)
            if ok and out:
                with open(save_path, "wb") as f:
                    f.write(out)
                if self._exec_out_ok is not True:
                    log.info("exec-out 截图路径可用")
                self._exec_out_ok = True
                return True
            # exec-out 失败，标记为不可用（下次直接回退）
            if self._exec_out_ok is not False:
                log.info("exec-out 截图超时/失败，后续使用回退路径")
            self._exec_out_ok = False

        if self._screenshot_fallback(save_path):
            log.info(f"截图回退路径成功: {save_path}")
            return True

        log.warning("截图失败")
        return False

    def tap(self, x: int, y: int):
        log.info(f"  👆 点击 ({x}, {y})")
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        log.info(f"  👆 滑动 ({x1},{y1}) -> ({x2},{y2}) {duration}ms")
        self._run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))

    def key(self, keycode: int):
        log.info(f"  ⌨️ 按键 keycode={keycode}")
        self._run("shell", "input", "keyevent", str(keycode))


# ==================== 图像匹配 ====================
def imread_cn(path: str):
    """支持中文路径的 imread"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def match_template(screenshot_path: str, template_path: str, threshold: float = 0.85):
    """
    返回 (匹配成功, 中心x, 中心y, 置信度)
    """
    if not os.path.exists(template_path):
        log.warning(f"模板不存在: {template_path}")
        return False, 0, 0, 0.0

    screen = imread_cn(screenshot_path)
    template = imread_cn(template_path)

    if screen is None or template is None:
        return False, 0, 0, 0.0

    sh, sw = screen.shape[:2]
    th, tw = template.shape[:2]

    if th > sh or tw > sw:
        log.warning(f"模板比截图大，跳过: {template_path}")
        return False, 0, 0, 0.0

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val >= threshold:
        center_x = max_loc[0] + tw // 2
        center_y = max_loc[1] + th // 2
        return True, center_x, center_y, max_val

    return False, 0, 0, max_val


# ==================== OCR 文字识别 ====================
_ocr = None

def _get_ocr():
    global _ocr
    if _ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            log.warning("rapidocr 未安装，正在安装...")
            subprocess.check_call(["uv", "sync"])
            from rapidocr_onnxruntime import RapidOCR
        log.info("正在初始化 OCR 模型...")
        _ocr = RapidOCR()
        log.info("OCR 模型就绪")
    return _ocr


def ocr_region(screenshot_path: str, region: list) -> str:
    """
    对截图的指定区域进行 OCR 文字识别
    region: [x1, y1, x2, y2]
    返回: 识别到的文字（去除空白）
    """
    screen = imread_cn(screenshot_path)
    if screen is None:
        return ""

    x1, y1, x2, y2 = region
    sh, sw = screen.shape[:2]
    x1 = max(0, min(x1, sw))
    y1 = max(0, min(y1, sh))
    x2 = max(0, min(x2, sw))
    y2 = max(0, min(y2, sh))

    if x2 <= x1 or y2 <= y1:
        return ""

    crop = screen[y1:y2, x1:x2]

    # 放大 2 倍提高识别率
    h, w = crop.shape[:2]
    crop = cv2.resize(crop, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    try:
        result, _ = _get_ocr()(crop)
        if result:
            # result: [[bbox, text, confidence], ...]
            texts = [item[1] for item in result]
            return "".join(texts).strip()
    except Exception as e:
        log.warning(f"OCR 调用失败: {e}")
    return ""


def parse_fraction(text: str):
    """
    解析 "X/Y" 格式的字符串
    返回: (分子, 分母) 或 (None, None)
    """
    text = text.replace(" ", "").replace("O", "0").replace("o", "0")
    parts = text.split("/")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return None, None


def _parse_post_adjust(raw):
    """解析 post_adjust 字符串列表为结构化数据"""
    adjusts = []
    if not raw:
        return adjusts
    for line in raw:
        parts = line.split()
        if len(parts) != 3:
            continue
        target_monitor, field, expr = parts
        op = expr[0]
        if op not in ("+", "-"):
            continue
        try:
            delta = int(expr[1:])
        except ValueError:
            continue
        adjusts.append({
            "monitor": target_monitor,
            "field": field,
            "op": op,
            "delta": delta,
        })
    return adjusts


class GameBot:
    def __init__(self, config_path: str, device_override: str | None = None,
                 on_screenshot=None, on_log=None, on_monitor=None,
                 single_shot: bool = False, on_active_task=None):
        self.on_screenshot = on_screenshot
        self.on_log = on_log
        self.on_monitor = on_monitor
        self.on_active_task = on_active_task
        self.single_shot = single_shot
        self._enabled_overrides = {}  # "task:name" -> bool, 动态覆盖启用状态
        if on_log:
            cb_handler = CallbackLogHandler(on_log)
            cb_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
            log.addHandler(cb_handler)
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        device = device_override or self.cfg.get("device", "")
        log.info(f"[DEBUG] GameBot 初始化: device={device}, single_shot={self.single_shot}")
        if not device or device == "192.168.1.100:5555":
            log.error("❌ 请先在 config.yaml 中设置你的设备 IP！")
            log.error("   device: \"你的IP:5555\"")
            sys.exit(1)

        adb_path = self.cfg.get("adb_path", "") or "adb"
        self.adb = ADB(device, adb_path)
        self.interval = float(self.cfg.get("interval", 1.0))
        self.threshold = float(self.cfg.get("threshold", 0.85))
        self.screenshot_dir = self.cfg.get("screenshot_dir", "screenshots")
        self._stop_requested = False
        self.tasks = [t for t in self.cfg.get("tasks", []) if t.get("enabled", True)]
        self.trigger_counts = {t["name"]: 0 for t in self.tasks}
        self.cooldowns = {t["name"]: 0.0 for t in self.tasks}

        # 步骤链
        self.chains = [c for c in self.cfg.get("chains", []) if c.get("enabled", True)]
        self.chain_state = {}  # name -> {"step": 0, "last_advance": timestamp, "retry_count": 0}
        for c in self.chains:
            self.chain_state[c["name"]] = {"step": 0, "last_advance": time.time(), "retry_count": 0}

        # 监控项（OCR 数值检测）
        self.monitors = [m for m in self.cfg.get("monitors", []) if m.get("enabled", True)]
        self.monitor_last_check = {}  # name -> timestamp
        self.monitor_values = {}      # name -> {"current": X, "total": Y, "value": Z}

        # 解析 post_adjust 配置
        self.task_post_adjust = {}  # name -> [adjustments]
        for t in self.tasks:
            adjusts = _parse_post_adjust(t.get("post_adjust", []))
            if adjusts:
                self.task_post_adjust[t["name"]] = adjusts
        for c in self.chains:
            adjusts = _parse_post_adjust(c.get("post_adjust", []))
            if adjusts:
                self.task_post_adjust[c["name"]] = adjusts

        Path(self.screenshot_dir).mkdir(exist_ok=True)

        log.info(f"已加载 {len(self.tasks)} 个独立任务, {len(self.chains)} 个步骤链, {len(self.monitors)} 个监控项")
        for t in self.tasks:
            log.info(f"  [独立] {t['name']}  模板: {t['template']}")
        for c in self.chains:
            steps_desc = []
            for s in c["steps"]:
                if "template" in s:
                    steps_desc.append(s["template"])
                elif s.get("action") == "tap_coord":
                    steps_desc.append(f"坐标({s['x']},{s['y']})")
                else:
                    steps_desc.append(s.get("action", "?"))
            log.info(f"  [链] {c['name']}  步骤: {' -> '.join(steps_desc)}")
        for m in self.monitors:
            log.info(f"  [监控] {m['name']}  区域: {m['region']}  间隔: {m.get('interval', 60)}s")

    def set_enabled_override(self, category: str, name: str, enabled: bool):
        """动态设置任务/链/监控的启用状态（运行时生效，无需重启）"""
        self._enabled_overrides[f"{category}:{name}"] = enabled
        action = "启用" if enabled else "禁用"
        log.info(f"🔄 动态{action}: [{category}] {name}")

    def _is_enabled(self, category: str, name: str) -> bool:
        """检查启用状态，优先使用动态覆盖"""
        key = f"{category}:{name}"
        if key in self._enabled_overrides:
            return self._enabled_overrides[key]
        return True  # 默认启用（已在初始化时过滤了 disabled 的）

    def _emit_active(self, category: str, name: str):
        """通知 GUI 当前活跃的任务/链"""
        if self.on_active_task:
            try:
                self.on_active_task(category, name)
            except Exception:
                pass

    def _apply_post_adjust(self, name: str):
        """任务/链执行后，按配置调整监控缓存值"""
        adjusts = self.task_post_adjust.get(name, [])
        if not adjusts:
            return
        for adj in adjusts:
            mname = adj["monitor"]
            mv = self.monitor_values.get(mname)
            if mv is None:
                continue
            field = adj["field"]
            if field not in mv:
                continue
            delta = adj["delta"] if adj["op"] == "+" else -adj["delta"]
            mv[field] = max(0, mv[field] + delta)
            log.info(f"🔧 [{name}] 调整 {mname}.{field}: {adj['op']}{adj['delta']} -> {mv[field]}")
        if self.on_monitor:
            self.on_monitor(dict(self.monitor_values))

    def _execute_action(self, task_def: dict, cx: int = 0, cy: int = 0):
        """执行一个动作（tap/swipe/key）"""
        action = task_def.get("action", "tap")
        if action == "tap":
            ox = task_def.get("offset_x", 0)
            oy = task_def.get("offset_y", 0)
            self.adb.tap(cx + ox, cy + oy)
        elif action == "swipe":
            sf = task_def.get("swipe_from", [cx, cy])
            st = task_def.get("swipe_to", [cx, cy])
            dur = task_def.get("duration", 300)
            self.adb.swipe(sf[0], sf[1], st[0], st[1], dur)
        elif action == "key":
            self.adb.key(task_def.get("keycode", 4))

    def _check_monitors(self, screenshot_path: str, now: float, force: bool = False):
        """检查所有监控项（OCR 数值检测），force=True 时忽略间隔"""
        for monitor in self.monitors:
            mname = monitor["name"]

            # 动态启用/禁用检查
            if not self._is_enabled("monitor", mname):
                continue

            if not force:
                interval = monitor.get("interval", 60)
                last = self.monitor_last_check.get(mname, 0)
                if now - last < interval:
                    continue

            self.monitor_last_check[mname] = now

            try:
                self._check_single_monitor(monitor, screenshot_path)
            except Exception as e:
                log.error(f"📊 [{mname}] 监控检测异常: {e}")
                import traceback
                log.error(f"📊 [{mname}] {traceback.format_exc()}")

    def _check_single_monitor(self, monitor: dict, screenshot_path: str):
        """检查单个监控项（OCR 数值检测）"""
        mname = monitor["name"]

        # 前置操作
        pre_type = monitor.get("pre_type", "tap" if monitor.get("pre_tap") else "none")
        if pre_type == "tap" and "pre_tap" in monitor:
            px, py = monitor["pre_tap"]
            log.info(f"📊 [{mname}] 前置点击 ({px},{py})")
            self.adb.tap(px, py)
            time.sleep(0.5)
            # 重新截图（页面已切换）
            if not self.adb.screenshot(screenshot_path):
                log.warning(f"📊 [{mname}] 截图失败，跳过")
                return
        elif pre_type == "template" and monitor.get("pre_template"):
            pre_template = monitor["pre_template"]
            matched, cx, cy, conf = match_template(
                screenshot_path, pre_template, self.threshold
            )
            if matched:
                log.info(f"📊 [{mname}] 前置匹配成功 ({cx},{cy}) 置信度={conf:.3f}，点击")
                self.adb.tap(cx, cy)
                time.sleep(0.5)
                if not self.adb.screenshot(screenshot_path):
                    log.warning(f"📊 [{mname}] 截图失败，跳过")
                    return
            else:
                skippable = monitor.get("pre_skippable", True)
                if skippable:
                    log.info(f"📊 [{mname}] 前置模板未匹配，跳过本次监控")
                    return
                else:
                    log.warning(f"📊 [{mname}] 前置模板未匹配，仍继续监控")

        # OCR 识别，失败时重试
        current, total = None, None
        for _attempt in range(3):
            text = ocr_region(screenshot_path, monitor["region"])
            current, total = parse_fraction(text)
            if current is not None and total is not None:
                break
            if _attempt < 2:
                log.warning(f"📊 [{mname}] OCR 识别失败(第{_attempt+1}次): '{text}'，重试...")
                time.sleep(0.3)

        # fixed_total: 总值已知时使用固定值，并校验 current 不超过 total
        fixed_total = monitor.get("fixed_total", 0)
        if fixed_total > 0:
            total = fixed_total
            if current is not None and current > total:
                # OCR 多识别了一位，从右侧逐步去掉重复/多余数字
                s = str(current)
                while len(s) > 1 and int(s) > total:
                    s = s[:-1]
                current = int(s) if s else None

        if current is not None and total is not None:
            report = monitor.get("report", "current")
            if report == "remaining":
                value = total - current
                log.info(f"📊 [{mname}] 队列: {current}/{total}  剩余: {value}")
            else:
                value = current
                log.info(f"📊 [{mname}] 体力: {current}/{total}")

            # 保存最新值，供链的跳过条件使用
            self.monitor_values[mname] = {"current": current, "total": total, "value": value}
            if self.on_monitor:
                self.on_monitor(dict(self.monitor_values))

            # 阈值提醒
            alert = monitor.get("alert_threshold", 0)
            if alert > 0 and value <= alert:
                log.warning(f"⚠️ [{mname}] 数值 {value} <= 阈值 {alert}！")
                beep()
        else:
            log.warning(f"📊 [{mname}] OCR 识别失败: '{text}'")

        # 关闭页面：匹配 close 模板并点击
        close_template = monitor.get("close_template")
        if close_template:
            if not self.adb.screenshot(screenshot_path):
                log.warning(f"📊 [{mname}] 关闭页面截图失败")
            else:
                matched, cx, cy, conf = match_template(
                    screenshot_path, close_template, self.threshold
                )
                if matched:
                    log.info(f"📊 [{mname}] 关闭页面 ({cx},{cy}) 置信度={conf:.3f}")
                    self.adb.tap(cx, cy)
                else:
                    log.warning(f"📊 [{mname}] 未匹配到关闭按钮: {close_template}")

    def run(self):
        log.info(f"[DEBUG] GameBot.run: 开始连接设备...")
        if not self.adb.connect():
            log.error("[DEBUG] GameBot.run: 设备连接失败，退出")
            sys.exit(1)

        mode_label = " (单次执行模式)" if self.single_shot else ""
        log.info(f"🤖 Bot 已启动{mode_label}，Ctrl+C 停止")
        log.info(f"   检查间隔: {self.interval}s  匹配阈值: {self.threshold}")
        log.info(f"[DEBUG] 任务数: {len(self.tasks)}, 链数: {len(self.chains)}, 监控数: {len(self.monitors)}")

        screenshot_path = os.path.join(self.screenshot_dir, "current.png")
        loop = 0
        single_shot_start = time.time() if self.single_shot else None
        single_shot_timeout = 120  # 单次执行最多120秒
        consecutive_failures = 0

        try:
            while not self._stop_requested:
                loop += 1
                now = time.time()

                # 截图
                try:
                    if not self.adb.screenshot(screenshot_path):
                        consecutive_failures += 1
                        log.warning(f"截图失败（连续{consecutive_failures}次），尝试恢复ADB...")
                        if consecutive_failures >= 3:
                            log.warning("连续截图失败3次，重启 ADB server...")
                            _run_subprocess([self.adb.adb, "kill-server"], timeout=5)
                            time.sleep(1)
                            _run_subprocess([self.adb.adb, "start-server"], timeout=10)
                            time.sleep(1)
                            consecutive_failures = 0
                        self.adb.connect()
                        time.sleep(self.interval * 2)
                        continue
                    else:
                        if consecutive_failures > 0:
                            log.info(f"截图恢复成功，之前连续失败{consecutive_failures}次")
                        consecutive_failures = 0
                except Exception as e:
                    log.error(f"[DEBUG] 截图异常: {type(e).__name__}: {e}")
                    time.sleep(self.interval * 2)
                    continue

                # GUI 回调：通知截图更新
                if self.on_screenshot:
                    try:
                        self.on_screenshot(screenshot_path)
                    except Exception:
                        pass

                # 保存调试截图
                if loop % 30 == 0:
                    ts = datetime.now().strftime("%H%M%S")
                    debug_path = os.path.join(self.screenshot_dir, f"debug_{ts}.png")
                    import shutil
                    shutil.copy(screenshot_path, debug_path)

                action_taken = False

                # 检查是否有链正在执行中
                chain_active = any(s["step"] > 0 for s in self.chain_state.values())

                # ---- 0. 首次循环：先采集监控数据再执行其他操作 ----
                if loop == 1 and not chain_active:
                    self._check_monitors(screenshot_path, now, force=True)
                    chain_active = any(s["step"] > 0 for s in self.chain_state.values())

                # ---- 1. 优先检查步骤链 ----
                for chain in self.chains:
                    cname = chain["name"]

                    # 动态启用/禁用检查
                    if not self._is_enabled("chain", cname):
                        continue

                    state = self.chain_state[cname]
                    step_idx = state["step"]
                    steps = chain["steps"]

                    # 前置条件检查：所有条件必须满足才执行链
                    skip_conditions = chain.get("skip_conditions", [])
                    if skip_conditions and step_idx == 0:
                        can_proceed = True
                        skip_reason = None
                        for cond in skip_conditions:
                            mname = cond["monitor"]
                            mv = self.monitor_values.get(mname)
                            if mv is None:
                                # 监控数据尚未采集，不能执行
                                can_proceed = False
                                skip_reason = f"{mname}=无数据"
                                break
                            field_val = mv.get(cond.get("field", "value"), 0)
                            op = cond.get("op", "<")
                            threshold = cond.get("value", 0)
                            if (op == "<" and field_val < threshold) or (op == "<=" and field_val <= threshold):
                                can_proceed = False
                                skip_reason = f"{mname}={field_val} (需>={threshold})"
                                break
                        if not can_proceed:
                            log.info(f"⏭️ [{cname}] 条件不满足，跳过: {skip_reason}")
                            continue

                    if step_idx >= len(steps):
                        # 链已完成，重置
                        state["step"] = 0
                        state["last_advance"] = now
                        continue

                    # 超时重置（链卡住太久）
                    reset_to = chain.get("reset_timeout", 30)
                    if now - state["last_advance"] > reset_to and step_idx > 0:
                        log.info(f"⏰ [{cname}] 超时 {reset_to}s 未推进，重置到第1步")
                        state["step"] = 0
                        state["last_advance"] = now
                        step_idx = 0

                    step_def = steps[step_idx]

                    # 冷却检查
                    chain_cd = state.get("cooldown_until", 0)
                    if now < chain_cd:
                        continue

                    # 支持无模板直接点击坐标
                    if step_def.get("action") == "tap_coord":
                        tx, ty = step_def.get("x", 0), step_def.get("y", 0)
                        log.info(f"🔗 [{cname}] 第{step_idx+1}步 点击坐标 ({tx},{ty})")
                        self._emit_active("chain", cname)
                        self.adb.tap(tx, ty)
                        state["step"] = step_idx + 1
                        state["last_advance"] = now
                        state["cooldown_until"] = now + step_def.get("cooldown", 1.0)
                        state["retry_count"] = 0  # 成功后重置重试计数
                        action_taken = True
                        if state["step"] >= len(steps):
                            log.info(f"🏁 [{cname}] 全部步骤完成！重置")
                            state["step"] = 0
                            beep()
                            self._apply_post_adjust(cname)
                            if self.single_shot:
                                self._stop_requested = True
                        break
                        continue

                    step_threshold = step_def.get("threshold", self.threshold)
                    matched, cx, cy, conf = match_template(
                        screenshot_path, step_def["template"], step_threshold
                    )

                    if matched:
                        log.info(f"🔗 [{cname}] 第{step_idx+1}步 匹配 ({cx},{cy}) 置信度={conf:.3f}")
                        self._emit_active("chain", cname)
                        self._execute_action(step_def, cx, cy)
                        state["step"] = step_idx + 1
                        state["last_advance"] = now
                        state["cooldown_until"] = now + step_def.get("cooldown", 1.0)
                        state["retry_count"] = 0  # 成功后重置重试计数
                        action_taken = True

                        if state["step"] >= len(steps):
                            log.info(f"🏁 [{cname}] 全部步骤完成！重置")
                            state["step"] = 0
                            beep()
                            self._apply_post_adjust(cname)
                            if self.single_shot:
                                self._stop_requested = True
                        break  # 一次只推进一个链的一步
                    else:
                        # 模板未匹配：如果步骤标记为可跳过，跳到下一步
                        if step_def.get("skippable", False):
                            log.info(f"⏭️ [{cname}] 第{step_idx+1}步 未匹配，跳过(可跳过步骤)")
                            state["step"] = step_idx + 1
                            state["last_advance"] = now
                            state["retry_count"] = 0
                            # 检查是否跳到了链末尾
                            if state["step"] >= len(steps):
                                log.info(f"🏁 [{cname}] 全部步骤完成！重置")
                                state["step"] = 0
                                beep()
                                self._apply_post_adjust(cname)
                                if self.single_shot:
                                    self._stop_requested = True
                            # 继续检查下一个链（不 break，让下一轮继续推进此链）
                            continue
                        else:
                            # 不可跳过步骤：重试一次，再次失败则放弃此链
                            retry = state.get("retry_count", 0)
                            if retry < 1:
                                log.warning(f"⚠️ [{cname}] 第{step_idx+1}步 未匹配，重试1次...")
                                state["retry_count"] = retry + 1
                                # 不推进步骤，下一轮重新匹配
                                break
                            else:
                                log.warning(f"⚠️ [{cname}] 第{step_idx+1}步 重试仍失败，放弃此链，继续下一个任务")
                                state["step"] = 0
                                state["retry_count"] = 0
                                state["last_advance"] = now
                                break

                if action_taken:
                    time.sleep(self.interval)
                    continue

                # ---- 2. 检查独立任务（链执行中时跳过） ----
                if not chain_active:
                    for task in self.tasks:
                        name = task["name"]

                        # 动态启用/禁用检查
                        if not self._is_enabled("task", name):
                            continue

                        max_t = task.get("max_triggers", 0)

                        if max_t > 0 and self.trigger_counts[name] >= max_t:
                            continue

                        if now < self.cooldowns[name]:
                            continue

                        matched, cx, cy, conf = match_template(
                            screenshot_path, task["template"], self.threshold
                        )

                        if matched:
                            log.info(f"✅ [{name}] 匹配成功 ({cx},{cy}) 置信度={conf:.3f}")
                            self._emit_active("task", name)
                            self._execute_action(task, cx, cy)
                            self.trigger_counts[name] += 1
                            self.cooldowns[name] = now + task.get("cooldown", 1.0)
                            action_taken = True
                            self._apply_post_adjust(name)
                            if self.single_shot:
                                self._stop_requested = True

                # ---- 3. 检查监控项（链执行中时跳过） ----
                if not chain_active:
                    self._check_monitors(screenshot_path, now)
                    # 单次执行且只有监控项时，检查完成后停止
                    if self.single_shot and not self.tasks and not self.chains and loop > 1:
                        self._stop_requested = True

                # 单次执行超时保护
                if self.single_shot and single_shot_start and now - single_shot_start > single_shot_timeout:
                    log.info(f"⏰ 单次执行超时 ({single_shot_timeout}s)，自动停止")
                    self._stop_requested = True

                time.sleep(self.interval)

        except KeyboardInterrupt:
            log.info("🛑 已停止")
            for name, count in self.trigger_counts.items():
                if count > 0:
                    log.info(f"   [独立] {name}: 触发了 {count} 次")
            for cname, state in self.chain_state.items():
                if state["step"] > 0:
                    log.info(f"   [链] {cname}: 执行到第{state['step']}步")
        except Exception as e:
            log.error(f"[DEBUG] 主循环异常: {e}")
            import traceback
            log.error(f"[DEBUG] {traceback.format_exc()}")

        log.info("[DEBUG] GameBot.run: 主循环退出")


# ==================== 辅助工具 ====================
def capture_template(device: str, adb_path: str = "adb"):
    """截一张图，方便你裁剪需要识别的按钮"""
    adb = ADB(device, adb_path)
    if not adb.connect():
        return
    path = f"template_capture_{datetime.now().strftime('%H%M%S')}.png"
    if adb.screenshot(path):
        log.info(f"✅ 截图已保存: {path}")
        log.info("   请用画图/PS/Snipaste 裁剪出你要识别的按钮，保存到 templates/ 目录")
    else:
        log.error("截图失败")


def test_match(screenshot: str, template: str, threshold: float = 0.85):
    """测试模板匹配效果"""
    matched, cx, cy, conf = match_template(screenshot, template, threshold)
    if matched:
        print(f"✅ 匹配成功！位置: ({cx}, {cy})  置信度: {conf:.3f}")
    else:
        print(f"❌ 未匹配  最高置信度: {conf:.3f}  (阈值: {threshold})")


# ==================== 入口 ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Android Auto Game")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--device", default=None, help="设备地址, 如 192.168.1.100:5555")
    parser.add_argument("--capture", action="store_true", help="仅截一张图用于制作模板")
    parser.add_argument("--test", nargs=2, metavar=("SCREENSHOT", "TEMPLATE"),
                        help="测试匹配: --test screenshot.png template.png")
    parser.add_argument("--threshold", type=float, default=None, help="覆盖匹配阈值")
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if args.capture:
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        dev = args.device or cfg.get("device", "")
        adb_p = cfg.get("adb_path", "") or "adb"
        capture_template(dev, adb_p)

    elif args.test:
        thr = args.threshold or 0.85
        test_match(args.test[0], args.test[1], thr)

    else:
        bot = GameBot(args.config, args.device)
        bot.run()

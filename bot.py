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
        winsound.Beep(800, 200)
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


# ==================== ADB 工具类 ====================
class ADB:
    def __init__(self, device: str, adb_path: str = "adb"):
        self.device = device
        self.adb = adb_path or "adb"

    def _run(self, *args, timeout=15):
        cmd = [self.adb, "-s", self.device] + list(args)
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr

    def connect(self) -> bool:
        log.info(f"正在连接设备: {self.device}")
        ok, out, err = subprocess.run(
            [self.adb, "connect", self.device],
            capture_output=True, timeout=10
        ), None, None
        ok, out, _ = ok.returncode == 0, ok.stdout.decode(), ok.stderr.decode()
        connected = "connected" in out or "already connected" in out
        if connected:
            log.info(f"✅ 已连接: {self.device}")
        else:
            log.error(f"❌ 连接失败: {out}")
        return connected

    def is_connected(self) -> bool:
        ok, out, _ = subprocess.run(
            [self.adb, "devices"], capture_output=True, timeout=5
        ), None, None
        ok = ok.stdout.decode()
        return self.device in ok

    def screenshot(self, save_path: str) -> bool:
        """截图并保存到本地"""
        ok, out, err = self._run("exec-out", "screencap", "-p", timeout=20)
        if ok and out:
            with open(save_path, "wb") as f:
                f.write(out)
            return True
        log.warning(f"截图失败: {err.decode()[:100]}")
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


class GameBot:
    def __init__(self, config_path: str, device_override: str | None = None):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        device = device_override or self.cfg.get("device", "")
        if not device or device == "192.168.1.100:5555":
            log.error("❌ 请先在 config.yaml 中设置你的设备 IP！")
            log.error("   device: \"你的IP:5555\"")
            sys.exit(1)

        adb_path = self.cfg.get("adb_path", "") or "adb"
        self.adb = ADB(device, adb_path)
        self.interval = float(self.cfg.get("interval", 1.0))
        self.threshold = float(self.cfg.get("threshold", 0.85))
        self.screenshot_dir = self.cfg.get("screenshot_dir", "screenshots")
        self.tasks = [t for t in self.cfg.get("tasks", []) if t.get("enabled", True)]
        self.trigger_counts = {t["name"]: 0 for t in self.tasks}
        self.cooldowns = {t["name"]: 0.0 for t in self.tasks}

        # 步骤链
        self.chains = [c for c in self.cfg.get("chains", []) if c.get("enabled", True)]
        self.chain_state = {}  # name -> {"step": 0, "last_advance": timestamp}
        for c in self.chains:
            self.chain_state[c["name"]] = {"step": 0, "last_advance": time.time()}

        # 监控项（OCR 数值检测）
        self.monitors = [m for m in self.cfg.get("monitors", []) if m.get("enabled", True)]
        self.monitor_last_check = {}  # name -> timestamp
        self.monitor_values = {}      # name -> {"current": X, "total": Y, "value": Z}

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
            if not force:
                interval = monitor.get("interval", 60)
                last = self.monitor_last_check.get(mname, 0)
                if now - last < interval:
                    continue

            self.monitor_last_check[mname] = now

            # 前置点击（如体力检测需要先打开页面）
            if "pre_tap" in monitor:
                px, py = monitor["pre_tap"]
                log.info(f"📊 [{mname}] 前置点击 ({px},{py})")
                self.adb.tap(px, py)
                time.sleep(0.5)
                # 重新截图（页面已切换）
                if not self.adb.screenshot(screenshot_path):
                    log.warning(f"📊 [{mname}] 截图失败，跳过")
                    continue

            text = ocr_region(screenshot_path, monitor["region"])
            current, total = parse_fraction(text)

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
                # 重新截图（确保最新画面）
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
        if not self.adb.connect():
            sys.exit(1)

        log.info("🤖 Bot 已启动，Ctrl+C 停止")
        log.info(f"   检查间隔: {self.interval}s  匹配阈值: {self.threshold}")

        screenshot_path = os.path.join(self.screenshot_dir, "current.png")
        loop = 0

        try:
            while True:
                loop += 1
                now = time.time()

                # 截图
                if not self.adb.screenshot(screenshot_path):
                    log.warning("截图失败，等待重试...")
                    time.sleep(self.interval * 2)
                    self.adb.connect()
                    continue

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
                        self.adb.tap(tx, ty)
                        state["step"] = step_idx + 1
                        state["last_advance"] = now
                        state["cooldown_until"] = now + step_def.get("cooldown", 1.0)
                        action_taken = True
                        if state["step"] >= len(steps):
                            log.info(f"🏁 [{cname}] 全部步骤完成！重置")
                            state["step"] = 0
                            beep()
                        break
                        continue

                    step_threshold = step_def.get("threshold", self.threshold)
                    matched, cx, cy, conf = match_template(
                        screenshot_path, step_def["template"], step_threshold
                    )

                    if matched:
                        log.info(f"🔗 [{cname}] 第{step_idx+1}步 匹配 ({cx},{cy}) 置信度={conf:.3f}")
                        self._execute_action(step_def, cx, cy)
                        state["step"] = step_idx + 1
                        state["last_advance"] = now
                        state["cooldown_until"] = now + step_def.get("cooldown", 1.0)
                        action_taken = True

                        if state["step"] >= len(steps):
                            log.info(f"🏁 [{cname}] 全部步骤完成！重置")
                            state["step"] = 0
                            beep()
                        break  # 一次只推进一个链的一步

                if action_taken:
                    time.sleep(self.interval)
                    continue

                # ---- 2. 检查独立任务（链执行中时跳过） ----
                if not chain_active:
                    for task in self.tasks:
                        name = task["name"]
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
                            self._execute_action(task, cx, cy)
                            self.trigger_counts[name] += 1
                            self.cooldowns[name] = now + task.get("cooldown", 1.0)
                            action_taken = True

                # ---- 3. 检查监控项（链执行中时跳过） ----
                if not chain_active:
                    self._check_monitors(screenshot_path, now)

                time.sleep(self.interval)

        except KeyboardInterrupt:
            log.info("🛑 已停止")
            for name, count in self.trigger_counts.items():
                if count > 0:
                    log.info(f"   [独立] {name}: 触发了 {count} 次")
            for cname, state in self.chain_state.items():
                if state["step"] > 0:
                    log.info(f"   [链] {cname}: 执行到第{state['step']}步")


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

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - 无尽冬日自动化 Bot"""

import os
import sys

block_cipher = None

# 项目根目录
ROOT = os.path.dirname(os.path.abspath(SPEC))

# 收集 rapidocr-onnxruntime 的模型文件
import rapidocr_onnxruntime
rapidocr_dir = os.path.dirname(rapidocr_onnxruntime.__file__)

# 收集 PySide6 所需的插件
from PySide6 import QtCore, QtWidgets
pyside6_dir = os.path.dirname(QtCore.__file__)

datas = [
    # rapidocr-onnxruntime 模型文件
    (rapidocr_dir, 'rapidocr_onnxruntime'),
    # PySide6 插件（平台插件等）
    (os.path.join(pyside6_dir, 'plugins', 'platforms'), 'PySide6/plugins/platforms'),
    (os.path.join(pyside6_dir, 'plugins', 'imageformats'), 'PySide6/plugins/imageformats'),
    (os.path.join(pyside6_dir, 'plugins', 'styles'), 'PySide6/plugins/styles'),
    # PySide6 translations
    (os.path.join(pyside6_dir, 'translations'), 'PySide6/translations'),
]

# 过滤掉不存在的路径
datas = [(src, dst) for src, dst in datas if os.path.exists(src)]

binaries = []

a = Analysis(
    ['gui.py'],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'bot',
        'rapidocr_onnxruntime',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtNetwork',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'PIL',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='无尽冬日-自动化',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, '图标.png') if os.path.exists(os.path.join(ROOT, '图标.png')) else None,
)

# live_zero_drop.spec
# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# =========================
# Collect heavy AI libs
# =========================
insight_datas, insight_bins, insight_hidden = collect_all('insightface')
onnx_datas, onnx_bins, onnx_hidden = collect_all('onnxruntime')
cv_datas, cv_bins, cv_hidden = collect_all('cv2')
numpy_datas, numpy_bins, numpy_hidden = collect_all('numpy')
faiss_datas, faiss_bins, faiss_hidden = collect_all('faiss')

# =========================
# Analysis
# =========================
a = Analysis(
    ['live_zero_drop.py'],               # your camera client script

    pathex=[],

    binaries=(
        insight_bins + onnx_bins + cv_bins + numpy_bins + faiss_bins
    ),

    datas=(
        insight_datas + onnx_datas + cv_datas + numpy_datas + faiss_datas +
        [
            ('config.yaml', '.'),
            ('utils', 'utils'),
            ('services', 'services'),
            ('models', 'models'),
            ('core', 'core'),
        ]
    ),

    hiddenimports=(
        insight_hidden + onnx_hidden + cv_hidden + numpy_hidden + faiss_hidden +
        [
            'cv2',
            'onnxruntime',
            'insightface',
            'skimage',
            'PIL',
            'faiss',
            'requests',
            'queue',
            'threading',
            'time',
            'numpy',
        ]
    ),

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# =========================
# PYZ
# =========================
pyz = PYZ(a.pure)

# =========================
# EXE
# =========================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FaceAttendanceCam',           # nicer name than 'live_zero_drop'
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['onnxruntime*.dll', 'onnxruntime_providers*.dll'],   # critical
    console=True,                        # keep visible for logs (or False for GUI-only)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# =========================
# COLLECT
# =========================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['onnxruntime*.dll', 'onnxruntime_providers*.dll'],
    name='FaceAttendanceCam',
)
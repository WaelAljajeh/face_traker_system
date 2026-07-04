# api_server.spec
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

# Web framework dependencies
uvicorn_datas, uvicorn_bins, uvicorn_hidden = collect_all('uvicorn')
fastapi_datas, fastapi_bins, fastapi_hidden = collect_all('fastapi')
pydantic_datas, pydantic_bins, pydantic_hidden = collect_all('pydantic')
sqlalchemy_datas, sqlalchemy_bins, sqlalchemy_hidden = collect_all('sqlalchemy')

# =========================
# Analysis
# =========================
a = Analysis(
    ['app.py'],                     # your main entry point for the API

    pathex=[],

    binaries=(
        insight_bins + onnx_bins + cv_bins + numpy_bins + faiss_bins +
        uvicorn_bins + fastapi_bins + pydantic_bins + sqlalchemy_bins
    ),

    datas=(
        insight_datas + onnx_datas + cv_datas + numpy_datas + faiss_datas +
        uvicorn_datas + fastapi_datas + pydantic_datas + sqlalchemy_datas +
        [
            ('config.yaml', '.'),          # your config file
            ('models', 'models'),          # ONNX / insightface model files
            ('utils', 'utils'),
            ('services', 'services'),
            ('core', 'core'),
            ('face_attendance.db', '.'),   # optional: include an empty/seed DB
        ]
    ),

    hiddenimports=(
        insight_hidden + onnx_hidden + cv_hidden + numpy_hidden + faiss_hidden +
        uvicorn_hidden + fastapi_hidden + pydantic_hidden + sqlalchemy_hidden +
        [
            'cv2',
            'onnxruntime',
            'insightface',
            'skimage',
            'PIL',
            'faiss',
            'uvicorn',
            'uvicorn.loops',
            'uvicorn.loops.auto',
            'uvicorn.protocols',
            'uvicorn.protocols.http',
            'uvicorn.protocols.http.auto',
            'fastapi',
            'pydantic',
            'pydantic.utils',
            'sqlalchemy',
            'sqlalchemy.sql',
            'sqlalchemy.orm',
            'sqlalchemy.ext',
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
# PYZ (Python bytecode)
# =========================
pyz = PYZ(a.pure)

# =========================
# EXE (single executable)
# =========================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FaceAttendanceAPI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['onnxruntime*.dll', 'onnxruntime_providers*.dll'],   # avoid corrupting ONNX
    console=True,                      # keep visible for logs (or set to False to hide)
    disable_windowed_traceback=False,
              
)

# =========================
# COLLECT (final output folder)
# =========================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['onnxruntime*.dll', 'onnxruntime_providers*.dll'],
    name='FaceAttendanceAPI',
) 
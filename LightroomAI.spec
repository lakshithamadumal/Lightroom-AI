# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

added_files = [
    ('web', 'web'),
    ('calibration', 'calibration'),
]

# Explicit minimal hidden imports required at runtime
hidden_imports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespans',
    'uvicorn.lifespans.on',
    'uvicorn.lifespans.off',
    'fastapi',
    'fastapi.staticfiles',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'starlette',
    'starlette.staticfiles',
    'starlette.middleware',
    'starlette.middleware.cors',
    'starlette.responses',
    'pydantic',
    'pydantic_core',
    'multipart',
    'multipart.multipart',
    'python_multipart',
    'PIL',
    'PIL.Image',
    'PIL.ImageCms',
    'PIL.ImageOps',
    'cv2',
    'numpy',
    'requests',
    'dotenv',
    'tkinter',
    'tkinter.filedialog',
    'webbrowser',
    'email.mime.text',
    'email.mime.multipart',
]

# Exclude all heavy and unneeded frameworks identified in the size audit
excluded_modules = [
    'torch',
    'torchvision',
    'torchaudio',
    'scipy',
    'scipy.libs',
    'pandas',
    'pandas.libs',
    'matplotlib',
    'imageio',
    'imageio_ffmpeg',
    'IPython',
    'ipykernel',
    'ipywidgets',
    'jupyter',
    'jupyter_client',
    'jupyter_core',
    'notebook',
    'nbformat',
    'nbconvert',
    'zmq',
    'tornado',
    'jedi',
    'parso',
    'lxml',
    'cryptography',
    'tests',
    'unittest',
    'pytest',
    'pip',
    'setuptools',
    'wheel',
]

a = Analysis(
    ['server.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out video-specific FFmpeg plugins and any stray CUDA/Torch DLLs
excluded_binary_patterns = [
    'opencv_videoio_ffmpeg',
    'torch',
    'cudnn',
    'cublas',
    'cufft',
    'cusparse',
    'cusolver',
    'curand',
    'nvrtc',
    'nvjitlink',
    'ffmpeg',
]

filtered_binaries = []
for b in a.binaries:
    name_lower = b[0].lower()
    if not any(pattern in name_lower for pattern in excluded_binary_patterns):
        filtered_binaries.append(b)

a.binaries = filtered_binaries

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LightroomAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Lightroom_AI_Studio_v2.0.0_Windows',
)

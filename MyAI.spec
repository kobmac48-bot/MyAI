import sys

from PyInstaller.utils.hooks import collect_all


datas = [("train_from_scratch.py", ".")]
binaries = []
hiddenimports = []
for package in ("torch", "transformers", "tokenizers", "accelerate", "safetensors"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

analysis = Analysis(
    ["myai.py"],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="MyAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="MyAI",
)
if sys.platform == "darwin":
    application = BUNDLE(
        collection,
        name="MyAI.app",
        bundle_identifier="com.kobmac48bot.myai",
    )

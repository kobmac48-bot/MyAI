import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files


legacy_client = os.environ.get("MYAI_LEGACY_CLIENT") == "1"
datas = []
binaries = []
hiddenimports = []
if legacy_client:
    datas.extend(collect_data_files("certifi"))
else:
    datas.append(("train_from_scratch.py", "."))
    for package in ("torch", "transformers", "tokenizers", "accelerate", "safetensors"):
        package_datas, package_binaries, package_hiddenimports = collect_all(package)
        datas.extend(package_datas)
        binaries.extend(package_binaries)
        hiddenimports.extend(package_hiddenimports)

analysis_options = {
    "pathex": [SPECPATH],
    "binaries": binaries,
    "datas": datas,
    "hiddenimports": sorted(set(hiddenimports)),
    "hookspath": [],
    "hooksconfig": {},
    "runtime_hooks": [],
    "excludes": [],
    "noarchive": False,
}
if not legacy_client:
    analysis_options["optimize"] = 0
analysis = Analysis(
    ["legacy_client.py" if legacy_client else "myai.py"],
    **analysis_options
)
pyz = PYZ(analysis.pure)
if sys.platform == "win32":
    executable = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="MyAI-windows-x86" if legacy_client else "MyAI",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
else:
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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path

spec_dir = Path(SPECPATH)
hiddenimports = collect_submodules("cxl_strata")
datas = collect_data_files("cxl_strata")
analysis = Analysis([str(spec_dir / "strata_entry.py")], pathex=[str(spec_dir.parent / "cli")], binaries=[], datas=datas,
                    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
                    runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="strata",
          console=True, disable_windowed_traceback=False)
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="strata")

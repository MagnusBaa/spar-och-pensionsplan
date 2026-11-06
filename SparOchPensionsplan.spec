# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['plan2030_app.py'],
    pathex=[],
    binaries=[],
    datas=[('Manual.pdf', '.'), ('pension.ico', '.')],
    hiddenimports=['plan_save', 'plan_engine', 'paminnelse', 'saldo_pdf', 'utdelning_core', 'utdelning_panel', 'aktiehandel_panel'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SparOchPensionsplan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['pension.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SparOchPensionsplan',
)

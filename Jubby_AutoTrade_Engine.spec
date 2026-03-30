# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = [('C:\\Users\\atrjk\\OneDrive\\바탕 화면\\Program\\04.Taemoo\\Jubby Project\\Jubby_AutoTrage_Python\\GUI\\Main.ui', 'GUI')]
binaries = []
datas += collect_data_files('xgboost')
datas += collect_data_files('lightgbm')
binaries += collect_dynamic_libs('xgboost')
binaries += collect_dynamic_libs('lightgbm')


a = Analysis(
    ['C:\\Users\\atrjk\\OneDrive\\바탕 화면\\Program\\04.Taemoo\\Jubby Project\\Jubby_AutoTrage_Python\\GUI\\FormMain.py'],
    pathex=['C:\\Users\\atrjk\\OneDrive\\바탕 화면\\Program\\04.Taemoo\\Jubby Project\\Jubby_AutoTrage_Python'],
    binaries=binaries,
    datas=datas,
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui', 'xgboost', 'lightgbm', 'FinanceDataReader', 'yfinance'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQtWebEngine', 'xgboost.testing', 'hypothesis'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Jubby_AutoTrade_Engine',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Jubby_AutoTrade_Engine',
)

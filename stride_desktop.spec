from PyInstaller.utils.hooks import collect_all


streamlit_datas, streamlit_binaries, streamlit_hidden = collect_all("streamlit")
webview_datas, webview_binaries, webview_hidden = collect_all("webview")

analysis = Analysis(
    ["desktop_app.py"],
    pathex=[],
    binaries=streamlit_binaries + webview_binaries,
    datas=streamlit_datas + webview_datas + [
        ("app.py", "."),
        ("event_feed.py", "."),
        (".streamlit/config.toml", ".streamlit"),
    ],
    hiddenimports=streamlit_hidden + webview_hidden + ["event_feed", "streamlit.web.bootstrap"],
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
    name="Stride",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)
collect = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="Stride",
)
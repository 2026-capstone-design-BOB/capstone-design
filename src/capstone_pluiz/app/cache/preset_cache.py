# app/cache/preset_cache.py
from app.cache.command_cache import CommandCache

PRESET_CACHE = {
    "screenshot": {
        "version": "1.0",
        "command": {"type": "system", "action": "screenshot", "params": {}},
        "code": "\n".join([
            "import subprocess, os, base64",
            "_L = [",
            '    "Add-Type -TypeDefinition @\'",',
            '    "using System;",',
            '    "using System.Runtime.InteropServices;",',
            '    "public class DPIHelper {",',
            '    "    [DllImport(\\"user32.dll\\")] public static extern bool SetProcessDPIAware();",',
            '    "    [DllImport(\\"user32.dll\\")] public static extern int GetSystemMetrics(int nIndex);",',
            '    "}",',
            '    "\'@",',
            '    "Add-Type -AssemblyName System.Drawing",',
            '    "[DPIHelper]::SetProcessDPIAware()",',
            '    "$w = [DPIHelper]::GetSystemMetrics(0)",',
            '    "$h = [DPIHelper]::GetSystemMetrics(1)",',
            '    "$ts = Get-Date -Format \'yyyyMMdd_HHmmss\'",',
            '    "$path = [System.IO.Path]::Combine($env:USERPROFILE, \'Desktop\', (\'screenshot_\' + $ts + \'.png\'))",',
            '    "$bmp = New-Object System.Drawing.Bitmap($w, $h)",',
            '    "$g = [System.Drawing.Graphics]::FromImage($bmp)",',
            '    "$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)",',
            '    "$bmp.Save($path)",',
            '    "$g.Dispose()",',
            '    "$bmp.Dispose()"',
            "]",
            'encoded = base64.b64encode("\\n".join(_L).encode("utf-16-le")).decode("ascii")',
            'subprocess.run(["powershell", "-EncodedCommand", encoded])',
            'print("스크린샷 저장: 바탕화면/screenshot_YYYYMMDD_HHMMSS.png")',
        ])
    }
}

# def init_preset_cache():
#     """앱 시작 시 1회 호출. 없는 항목만 삽입, 버전 다르면 업데이트."""
#     cache = CommandCache()
#     for key, item in PRESET_CACHE.items():
#         existing = cache.get(item["command"])
#         if not existing:
#             cache.save(item["command"], item["code"])
#             print(f"[Preset] 초기 캐시 삽입: {key} v{item['version']}")
#         else:
#             print(f"[Preset] 이미 존재: {key}")
# test_security.py
from app.security.ast_guard import check_code
import os

print("=== 차단 테스트 ===")
print(check_code('import os\nos.remove("test.txt")'))
print(check_code('import winreg'))
print(check_code('eval("os.system(\'format c:\')")'))

print("\n=== 허용 테스트 ===")
print(check_code('import subprocess\nsubprocess.Popen(["notepad.exe"])'))
print(check_code('from selenium import webdriver'))

print("\n=== 로그 확인 ===")
log_path = "app/security/security.log"
if os.path.exists(log_path):
    with open(log_path, "r", encoding="utf-8") as f:
        print(f.read())
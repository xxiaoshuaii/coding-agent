import subprocess

def run_cmd(cmd: str) -> tuple:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return f"运行失败: {e}", "", -1

stdout, stderr, code = run_cmd("java --version")
print(f"stdout: {stdout}")
print(f"stderr: {stderr}")
print(f"returncode: {code}")

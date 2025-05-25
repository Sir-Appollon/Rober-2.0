import time
import subprocess

INTERVAL_SECONDS = 600  # 10 minutes

def run_quick_check():
    result = subprocess.run(["python3", "/app/run_quick_check.py"], capture_output=True, text=True)
    return "FAILURE" in result.stdout

def run_diagnostic():
    subprocess.run(["python3", "/app/Health_monit.py"])

if __name__ == "__main__":
    while True:
        if run_quick_check():
            run_diagnostic()
        time.sleep(INTERVAL_SECONDS)

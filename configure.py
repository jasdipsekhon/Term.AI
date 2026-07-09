import sys
import os
import json
import glob
import tempfile

project_dir = sys.argv[1].strip('"').rstrip("\\/")
python_exe  = os.path.join(project_dir, ".venv", "Scripts", "python.exe")
main_py     = os.path.join(project_dir, "main.py")

localappdata = os.environ.get("LOCALAPPDATA", "")
appdata      = os.environ.get("APPDATA", "")

if not localappdata or not appdata:
    print("ERROR: LOCALAPPDATA or APPDATA environment variable is not set.")
    sys.exit(1)

candidates = glob.glob(os.path.join(
    localappdata, "Packages", "Claude_*",
    "LocalCache", "Roaming", "Claude", "claude_desktop_config.json"
))
candidates.append(os.path.join(appdata, "Claude", "claude_desktop_config.json"))

config_path = next((p for p in candidates if os.path.exists(p)), None)

if config_path is None:
    config_path = candidates[-1]
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    config = {}
else:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

config.setdefault("mcpServers", {})["Term.AI"] = {
    "command": python_exe,
    "args":    [main_py],
    "cwd":     project_dir,
}

tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(config_path), suffix=".tmp")
try:
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp_path, config_path)
except Exception:
    os.unlink(tmp_path)
    raise

print("Config updated:", config_path)

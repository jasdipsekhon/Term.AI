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

store_config_paths = glob.glob(os.path.join(
    localappdata, "Packages", "Claude_*",
    "LocalCache", "Roaming", "Claude", "claude_desktop_config.json"
))
regular_config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")

candidates = store_config_paths + [regular_config_path]
config_path = next((p for p in candidates if os.path.exists(p)), None)

if config_path is None:
    # Neither config file exists yet -- first-time setup. Prefer the Store
    # install if its package folder exists, even though it hasn't created its
    # config file yet (that only happens the first time the app itself runs).
    store_package_dirs = glob.glob(os.path.join(localappdata, "Packages", "Claude_*"))
    if store_package_dirs:
        config_path = os.path.join(store_package_dirs[0], "LocalCache", "Roaming", "Claude", "claude_desktop_config.json")
    else:
        config_path = regular_config_path
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

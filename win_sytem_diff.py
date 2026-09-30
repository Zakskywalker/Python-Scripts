import os
import sys
import json
import winreg
from datetime import datetime

# Common target directories to inspect
FS_TARGETS = [
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.environ.get("ProgramData", r"C:\ProgramData"),
    os.environ.get("LOCALAPPDATA", ""),
    os.environ.get("APPDATA", ""),
]

# High-impact registry hives and subkeys commonly altered during software installs
REG_TARGETS = [
    (winreg.HKEY_LOCAL_MACHINE, r"Software"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")
]

HIVE_NAMES = {
    winreg.HKEY_LOCAL_MACHINE: "HKLM",
    winreg.HKEY_CURRENT_USER: "HKCU"
}

def scan_filesystem(target_paths):
    """Recursively records files with modification timestamp and byte size."""
    fs_snapshot = {}
    for base in target_paths:
        if not base or not os.path.exists(base):
            continue
        for root, _, files in os.walk(base):
            for file in files:
                full_path = os.path.join(root, file)
                try:
                    stat = os.stat(full_path)
                    fs_snapshot[full_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size
                    }
                except (PermissionError, FileNotFoundError):
                    continue
    return fs_snapshot

def scan_registry(targets):
    """Recursively walks registry keys and values."""
    reg_snapshot = {}

    def _walk_key(hive_handle, hive_label, subkey_path, depth=0, max_depth=5):
        if depth > max_depth:
            return
        try:
            with winreg.OpenKey(hive_handle, subkey_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                # Enumerate values
                idx = 0
                while True:
                    try:
                        val_name, val_data, _ = winreg.EnumValue(key, idx)
                        full_entry = f"{hive_label}\\{subkey_path} -> [{val_name}]"
                        reg_snapshot[full_entry] = str(val_data)[:256]
                        idx += 1
                    except OSError:
                        break

                # Enumerate child keys
                idx = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, idx)
                        child_path = f"{subkey_path}\\{sub}"
                        _walk_key(hive_handle, hive_label, child_path, depth + 1, max_depth)
                        idx += 1
                    except OSError:
                        break
        except (PermissionError, FileNotFoundError, OSError):
            return

    for root_hive, subkey in targets:
        _walk_key(root_hive, HIVE_NAMES[root_hive], subkey)

    return reg_snapshot

def take_snapshot():
    print("[*] Recording filesystem state...")
    fs = scan_filesystem(FS_TARGETS)
    print(f"    Indexed {len(fs):,} files.")

    print("[*] Recording registry state...")
    reg = scan_registry(REG_TARGETS)
    print(f"    Indexed {len(reg):,} registry values.")

    return {"filesystem": fs, "registry": reg}

def compute_diff(before, after):
    diff = {
        "fs_added": [],
        "fs_modified": [],
        "fs_removed": [],
        "reg_added": {},
        "reg_modified": {},
        "reg_removed": []
    }

    # Filesystem differences
    for path, meta in after["filesystem"].items():
        if path not in before["filesystem"]:
            diff["fs_added"].append(path)
        elif meta["mtime"] != before["filesystem"][path]["mtime"] or meta["size"] != before["filesystem"][path]["size"]:
            diff["fs_modified"].append(path)

    for path in before["filesystem"]:
        if path not in after["filesystem"]:
            diff["fs_removed"].append(path)

    # Registry differences
    for key, val in after["registry"].items():
        if key not in before["registry"]:
            diff["reg_added"][key] = val
        elif val != before["registry"][key]:
            diff["reg_modified"][key] = {"old": before["registry"][key], "new": val}

    for key in before["registry"]:
        if key not in after["registry"]:
            diff["reg_removed"].append(key)

    return diff

def main():
    if sys.platform != "win32":
        print("[-] This utility requires Windows.")
        return

    print("=====================================================")
    print("        Windows Installation Differential Scraper    ")
    print("=====================================================")

    print("\nPhase 1: Taking baseline snapshot BEFORE installation...")
    baseline = take_snapshot()

    input("\n[!] Install the target application now. Once finished, press [Enter] to scan changes: ")

    print("\nPhase 2: Taking post-installation snapshot...")
    postline = take_snapshot()

    print("\n[*] Calculating delta...")
    delta = compute_diff(baseline, postline)

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "summary_counts": {
            "files_added": len(delta["fs_added"]),
            "files_modified": len(delta["fs_modified"]),
            "files_removed": len(delta["fs_removed"]),
            "registry_keys_added": len(delta["reg_added"]),
            "registry_keys_modified": len(delta["reg_modified"]),
            "registry_keys_removed": len(delta["reg_removed"])
        },
        "changes": delta
    }

    output_file = "installation_diff.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n================ Results Summary ================")
    print(f" Files Added:          {len(delta['fs_added'])}")
    print(f" Files Modified:       {len(delta['fs_modified'])}")
    print(f" Files Removed:        {len(delta['fs_removed'])}")
    print(f" Registry Keys Added:  {len(delta['reg_added'])}")
    print(f" Registry Keys Changed:{len(delta['reg_modified'])}")
    print(f" Registry Keys Removed:{len(delta['reg_removed'])}")
    print("=================================================")
    print(f"[+] Full delta report exported to: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    main()
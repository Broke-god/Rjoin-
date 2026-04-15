"""
Roblox Clone Error Monitor — Android / Termux (Root)
=====================================================
Cycles through each Roblox clone, brings it to the foreground,
screenshots it, and checks for an error/disconnect box visually.
If one is found (or if it's closed), it relaunches directly into the Game ID.

SETUP
─────
1. Install dependencies in Termux:
     pkg update
     pkg install python opencv python-numpy
     pip install pillow

2. Place your 3 reference images in the SAME folder as this script:
     error_template_1.jpg   ← white "Connection error" box
     error_template_2.jpg   ← dark  "Connection Error" modal
     error_template_3.jpg   ← dark  "Disconnected / Error 277" modal

3. Run:
     python roblox_monitor.py
"""

import os
import sys
import time
import subprocess
from datetime import datetime

import cv2
import numpy as np

# ─────────────────────── CONFIGURATION ───────────────────────────────────────

# Add your target Game/Place ID here to directly open the game.
# If you just want to open the main menu, set this to None or ""
GAME_ID = "123456789"  

# Your clone package names
PACKAGES = [
    "com.roblox.clienv",
    "com.roblox.clienw",
    "com.roblox.clienx",
    "com.roblox.clieny",
]

# Template images — place in same folder as this script
SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILES = [
    os.path.join(SCRIPT_DIR, "error_template_1.jpg"),
    os.path.join(SCRIPT_DIR, "error_template_2.jpg"),
    os.path.join(SCRIPT_DIR, "error_template_3.jpg"),
]

# Visual match sensitivity  (0.0–1.0)
MATCH_THRESHOLD = 0.58

# Seconds between full scan cycles
CHECK_INTERVAL = 6

# After restarting a clone, ignore it for this long to allow game load
COOLDOWN_SECONDS = 50

# Seconds to wait after switching an app to foreground before screenshotting
SWITCH_WAIT = 4.0

# Temp screenshot path (root-writable, readable by Termux after chmod)
SCREENSHOT_PATH = "/data/local/tmp/rbx_check.png"

# ──────────────────────────────────────────────────────────────────────────────


def run_root(cmd: str) -> tuple[int, str, str]:
    """Run a shell command as root via su -c."""
    result = subprocess.run(
        ["su", "-c", cmd],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def check_root() -> bool:
    code, out, _ = run_root("id")
    return "uid=0" in out


def get_launch_activity(package: str) -> str | None:
    """Try to resolve the LAUNCHER activity for a package."""
    _, out, _ = run_root(
        f"cmd package resolve-activity --brief "
        f"-a android.intent.action.MAIN "
        f"-c android.intent.category.LAUNCHER {package}"
    )
    for line in out.strip().splitlines():
        line = line.strip()
        if "/" in line and not line.startswith("No"):
            return line
    return None


def bring_to_foreground(package: str):
    """Resume a running package without forcing a new intent state."""
    activity = get_launch_activity(package)
    if activity:
        run_root(f"am start -n {activity}")
    else:
        run_root(
            f"monkey -p {package} "
            f"-c android.intent.category.LAUNCHER 1"
        )
    time.sleep(SWITCH_WAIT)


def take_screenshot() -> bool:
    """Take a full-screen screenshot as root, then make it readable."""
    code, _, err = run_root(f"screencap -p {SCREENSHOT_PATH}")
    if code != 0:
        print(f"    [WARN] screencap failed: {err.strip()}")
        return False
    run_root(f"chmod 644 {SCREENSHOT_PATH}")
    return os.path.exists(SCREENSHOT_PATH)


def force_stop(package: str):
    run_root(f"am force-stop {package}")
    time.sleep(1.5)


def launch_package(package: str, game_id: str = None):
    """Launch / relaunch a package, optionally into a specific game."""
    if game_id and str(game_id).strip() != "":
        cmd = f'am start -a android.intent.action.VIEW -d "roblox://placeId={game_id}" -p {package}'
        run_root(cmd)
    else:
        activity = get_launch_activity(package)
        if activity:
            run_root(f"am start -n {activity}")
        else:
            run_root(
                f"monkey -p {package} "
                f"-c android.intent.category.LAUNCHER 1"
            )


def is_running(package: str) -> bool:
    """Return True if the package has a live process."""
    _, out, _ = run_root(f"pidof {package}")
    return bool(out.strip())


# ───────────────────────── TEMPLATE MATCHING ──────────────────────────────────

def load_templates(paths: list) -> list:
    templates = []
    for p in paths:
        if not os.path.exists(p):
            print(f"  [WARN] Template not found — skipping: {os.path.basename(p)}")
            continue
        img = cv2.imread(p)
        if img is None:
            print(f"  [WARN] Could not read — skipping: {os.path.basename(p)}")
            continue
        templates.append(img)
        print(f"  [ OK] Loaded: {os.path.basename(p)}")
    return templates


def has_error_box(screenshot_path: str, templates: list) -> tuple[bool, np.ndarray | None]:
    """
    Grayscale template matching to find the disconnect popup.
    Returns: (is_match_found, annotated_image_data)
    """
    screen = cv2.imread(screenshot_path)
    if screen is None:
        return False, None

    gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    sh, sw = gray_screen.shape

    for tmpl in templates:
        gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        th, tw = gray_tmpl.shape

        for scale in np.linspace(0.40, 1.60, 20):
            nw = int(tw * scale)
            nh = int(th * scale)

            if nw >= sw or nh >= sh or nw < 20 or nh < 20:
                continue

            resized = cv2.resize(gray_tmpl, (nw, nh), interpolation=cv2.INTER_AREA)
            result  = cv2.matchTemplate(gray_screen, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= MATCH_THRESHOLD:
                # MATCH FOUND! Calculate center for the circle
                top_left = max_loc
                center_x = top_left[0] + nw // 2
                center_y = top_left[1] + nh // 2
                radius = int(max(nw, nh) * 0.7) # Make circle slightly larger than the match box

                # Draw a thick RED circle (BGR format: 0, 0, 255)
                cv2.circle(screen, (center_x, center_y), radius, (0, 0, 255), 12)
                
                # Draw a GREEN bounding box inside just to be precise
                bottom_right = (top_left[0] + nw, top_left[1] + nh)
                cv2.rectangle(screen, top_left, bottom_right, (0, 255, 0), 4)

                # Add text overlay showing the exact confidence percentage
                text = f"Match: {max_val*100:.1f}%"
                cv2.putText(screen, text, (top_left[0], max(30, top_left[1] - 20)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 4, cv2.LINE_AA)

                return True, screen

    return False, None


# ──────────────────────────────── MAIN ────────────────────────────────────────

def main():
    print("=" * 54)
    print("   Roblox Clone Error Monitor  —  Android / Root")
    print("=" * 54)

    print("\n  Checking root access...", end=" ")
    if not check_root():
        print("FAILED\n")
        print("[ERROR] Could not get root. Make sure Termux has su access.")
        sys.exit(1)
    print("OK")

    print("\n  Loading templates:")
    templates = load_templates(TEMPLATE_FILES)
    if not templates:
        print("\n[ERROR] No templates loaded. "
              "Put the 3 jpg files next to this script and retry.")
        sys.exit(1)

    print(f"\n  Packages monitored : {len(PACKAGES)}")
    print(f"  Target Game ID     : {GAME_ID if GAME_ID else 'None (Main Menu)'}")
    print(f"  Check interval     : {CHECK_INTERVAL}s")
    print("\n  Running — Ctrl+C to stop.\n")
    print("-" * 54)

    cooldowns: dict[str, float] = {}

    while True:
        try:
            for pkg in PACKAGES:

                elapsed = time.time() - cooldowns.get(pkg, 0)
                if elapsed < COOLDOWN_SECONDS:
                    remaining = int(COOLDOWN_SECONDS - elapsed)
                    print(f"  [--] {pkg}  (cooldown {remaining}s left)")
                    continue

                if not is_running(pkg):
                    print(f"  [++] {pkg}  (not running) -> Launching instance...")
                    launch_package(pkg, GAME_ID)
                    cooldowns[pkg] = time.time()
                    continue

                print(f"  [>>] {pkg}")
                bring_to_foreground(pkg)

                if not take_screenshot():
                    print(f"       Screenshot failed — skipping")
                    continue

                is_error, annotated_img = has_error_box(SCREENSHOT_PATH, templates)
                
                if is_error and annotated_img is not None:
                    print(f"\n  [!!!] ERROR BOX DETECTED  ——  {pkg}")
                    
                    # --- Save the newly drawn circled image ---
                    debug_name = f"error_caught_{pkg.split('.')[-1]}_{int(time.time())}.png"
                    local_tmp_img = f"/data/local/tmp/{debug_name}"
                    
                    # Write the image locally using OpenCV
                    cv2.imwrite(local_tmp_img, annotated_img)
                    
                    # Move it to the Downloads folder
                    run_root(f"mv {local_tmp_img} /sdcard/Download/{debug_name}")
                    print(f"        → Saved circled evidence to Downloads/{debug_name}")
                    # ------------------------------------------

                    print(f"        → Force stopping...")
                    force_stop(pkg)
                    print(f"        → Relaunching into Game ID: {GAME_ID}...")
                    launch_package(pkg, GAME_ID)
                    cooldowns[pkg] = time.time()
                    print(f"        → Done. Cooldown started ({COOLDOWN_SECONDS}s).\n")
                else:
                    print(f"       [ ✓] No error box found")

            print(f"\n  Cycle done — waiting {CHECK_INTERVAL}s...\n")
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nStopped by user.")
            break
        except Exception as exc:
            print(f"\n[ERR] Unexpected error: {exc}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

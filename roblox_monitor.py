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

2. Place your 3 reference images in the SAME folder as this script:
     error_template_1.jpg   ← white "Connection error" box
     error_template_2.jpg   ← dark  "Connection Error" modal
     error_template_3.jpg   ← dark  "Disconnected / Error 277" modal

3. Run:
     python roblox_monitor.py
"""

import argparse
import logging
import os
import sys
import time
import subprocess
from typing import List, Optional, Tuple

import cv2
import numpy as np

# ─────────────────────── CONFIGURATION ───────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Roblox Clone Error Monitor")
    parser.add_argument(
        "--game-id",
        type=str,
        default=None,
        help="Target Game/Place ID (optional, launches to main menu if not specified)"
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        default=[
            "com.roblox.clienv",
            "com.roblox.clienw",
            "com.roblox.clienx",
            "com.roblox.clieny",
        ],
        help="Clone package names (default: standard clones)"
    )
    parser.add_argument(
        "--match-threshold",
        type=float,
        default=0.58,
        help="Visual match sensitivity (0.0-1.0, default: 0.58)"
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=6,
        help="Seconds between scan cycles (default: 6)"
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=50,
        help="Cooldown after restart (default: 50)"
    )
    parser.add_argument(
        "--switch-wait",
        type=float,
        default=4.0,
        help="Wait after switching app (default: 4.0)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    return parser.parse_args()


def check_dependencies() -> None:
    """Check if required dependencies are installed."""
    try:
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401
    except ImportError as e:
        logging.error(f"Missing dependency: {e}")
        sys.exit(1)


# Default template files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILES = [
    os.path.join(SCRIPT_DIR, "error_template_1.jpg"),
    os.path.join(SCRIPT_DIR, "error_template_2.jpg"),
    os.path.join(SCRIPT_DIR, "error_template_3.jpg"),
]

# Temp screenshot path
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


def bring_to_foreground(package: str) -> None:
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
        logging.warning(f"screencap failed: {err.strip()}")
        return False
    run_root(f"chmod 644 {SCREENSHOT_PATH}")
    return os.path.exists(SCREENSHOT_PATH)


def force_stop(package: str) -> None:
    run_root(f"am force-stop {package}")
    time.sleep(1.5)


def launch_package(package: str, game_id: Optional[str] = None) -> None:
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

def load_templates(paths: List[str]) -> List[np.ndarray]:
    templates = []
    for p in paths:
        if not os.path.exists(p):
            logging.warning(f"Template not found — skipping: {os.path.basename(p)}")
            continue
        img = cv2.imread(p)
        if img is None:
            logging.warning(f"Could not read — skipping: {os.path.basename(p)}")
            continue
        templates.append(img)
        logging.info(f"Loaded: {os.path.basename(p)}")
    return templates


def has_error_box(screenshot_path: str, templates: List[np.ndarray], threshold: float) -> Tuple[bool, Optional[np.ndarray]]:
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

            if max_val >= threshold:
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

def setup_logging(log_level: str) -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def validate_inputs(args: argparse.Namespace) -> None:
    """Validate command-line arguments."""
    if args.game_id and args.game_id.strip():
        try:
            int(args.game_id)
        except ValueError:
            logging.error("GAME_ID must be a valid integer")
            sys.exit(1)
    for pkg in args.packages:
        if not pkg.startswith("com."):
            logging.warning(f"Package {pkg} does not look like a valid Android package name")


def monitor_packages(
    packages: List[str],
    game_id: Optional[str],
    templates: List[np.ndarray],
    match_threshold: float,
    check_interval: int,
    cooldown_seconds: int
) -> None:
    """Main monitoring loop."""
    cooldowns: dict[str, float] = {}

    while True:
        try:
            for pkg in packages:
                elapsed = time.time() - cooldowns.get(pkg, 0)
                if elapsed < cooldown_seconds:
                    remaining = int(cooldown_seconds - elapsed)
                    logging.info(f"{pkg} (cooldown {remaining}s left)")
                    continue

                if not is_running(pkg):
                    logging.info(f"{pkg} (not running) -> Launching instance...")
                    launch_package(pkg, game_id)
                    cooldowns[pkg] = time.time()
                    continue

                logging.info(f"Checking {pkg}")
                bring_to_foreground(pkg)

                if not take_screenshot():
                    logging.warning("Screenshot failed — skipping")
                    continue

                is_error, annotated_img = has_error_box(SCREENSHOT_PATH, templates, match_threshold)
                
                if is_error and annotated_img is not None:
                    logging.warning(f"ERROR BOX DETECTED — {pkg}")
                    
                    # Save the newly drawn circled image
                    debug_name = f"error_caught_{pkg.split('.')[-1]}_{int(time.time())}.png"
                    local_tmp_img = f"/data/local/tmp/{debug_name}"
                    
                    cv2.imwrite(local_tmp_img, annotated_img)
                    run_root(f"mv {local_tmp_img} /sdcard/Download/{debug_name}")
                    logging.info(f"Saved circled evidence to Downloads/{debug_name}")

                    logging.info("Force stopping...")
                    force_stop(pkg)
                    logging.info(f"Relaunching into Game ID: {game_id}...")
                    launch_package(pkg, game_id)
                    cooldowns[pkg] = time.time()
                    logging.info(f"Done. Cooldown started ({cooldown_seconds}s).")
                else:
                    logging.info("No error box found")

            logging.info(f"Cycle done — waiting {check_interval}s...")
            time.sleep(check_interval)

        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            break
        except Exception as exc:
            logging.error(f"Unexpected error: {exc}")
            time.sleep(check_interval)


def main() -> None:
    """Main entry point."""
    check_dependencies()
    args = parse_args()
    validate_inputs(args)
    setup_logging(args.log_level)

    logging.info("=" * 54)
    logging.info("   Roblox Clone Error Monitor  —  Android / Root")
    logging.info("=" * 54)

    logging.info("Checking root access...")
    if not check_root():
        logging.error("Could not get root. Make sure Termux has su access.")
        sys.exit(1)
    logging.info("Root access OK")

    logging.info("Loading templates:")
    templates = load_templates(TEMPLATE_FILES)
    if not templates:
        logging.error("No templates loaded. Put the 3 jpg files next to this script and retry.")
        sys.exit(1)

    logging.info(f"Packages monitored: {len(args.packages)}")
    logging.info(f"Target Game ID: {args.game_id if args.game_id else 'None (Main Menu)'}")
    logging.info(f"Check interval: {args.check_interval}s")
    logging.info("Running — Ctrl+C to stop.")

    monitor_packages(
        args.packages,
        args.game_id,
        templates,
        args.match_threshold,
        args.check_interval,
        args.cooldown_seconds
    )


if __name__ == "__main__":
    main()

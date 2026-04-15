# Rjoin-
Watchdog rejoin script for Roblox clones on Android/Termux (Root).

## Description
This script monitors multiple Roblox clone apps, detects error/disconnect dialogs visually using OpenCV template matching, and automatically relaunches them into the specified Game ID.

## Features
- Monitors multiple Roblox clones simultaneously
- Visual error detection with configurable sensitivity
- Automatic relaunch with cooldown to prevent rapid restarts
- Saves debug images of detected errors
- Configurable via command-line arguments
- Proper logging and error handling

## Setup
1. Install dependencies in Termux:
   ```
   pkg update
   pkg install python opencv python-numpy
   ```

2. Place your 3 reference images in the same folder as the script:
   - `error_template_1.jpg` ← white "Connection error" box
   - `error_template_2.jpg` ← dark "Connection Error" modal
   - `error_template_3.jpg` ← dark "Disconnected / Error 277" modal

3. Run:
   ```
   python roblox_monitor.py --help
   python roblox_monitor.py --game-id 123456789
   ```

## Command-Line Options
- `--game-id`: Target Game/Place ID (default: 123456789)
- `--packages`: List of clone package names (default: standard Roblox clones)
- `--match-threshold`: Visual match sensitivity (0.0-1.0, default: 0.58)
- `--check-interval`: Seconds between scan cycles (default: 6)
- `--cooldown-seconds`: Cooldown after restart (default: 50)
- `--switch-wait`: Wait after switching app (default: 4.0)
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR; default: INFO)

## Requirements
- Android device with root access
- Termux with su permissions
- OpenCV and NumPy installed
- 3 template images for error detection

## Notes
- Supports only Delta for now (as per original)
- Requires root for screenshot and app control commands
- Debug images are saved to `/sdcard/Download/`

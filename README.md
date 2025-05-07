# Flaccup: FLAC Integrity Checker and Backup Utility

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) `flaccup` is a tool for backing up and verifying the integrity of FLAC files. It is designed to run as an automated task (with Cron or other), with incremented verification and backup checks across an entire library. `flaccup` leverages `flac` (for integrity tests), `metaflac` (for audio MD5 checksums), and `rsync` (for efficient backups).

## Features

* **FLAC Integrity Verification:** Uses `flac -t` to test files for corruption.
* **Audio MD5 Checksumming:** Generates and compares MD5 checksums of the audio stream (via `metaflac --show-md5sum`) to detect changes in audio data, ignoring metadata changes.
* **SQLite Database:** Stores metadata, scan history, integrity status, MD5 checksums, and backup dates for every FLAC file in your library.
* **Configuration Wizard:** A first-run setup wizard (`wizard.py`) guides you through initial configuration.
* **Detailed Logging:** `flaccup` creates comprehensive log files for each run, detailing any actions taken and any issues found.
* **File Management:** Detects new files added to your library and files that have been removed.
* **Scheduled Rescans:** Allows configuration of how often files should be re-verified and re-checked.
* **Scan Load Distribution:** `flaccup` includes a scheduler utility, which prevents a massive load on any single day.

## How It Works

1.  **Configuration:** On first run (or via `flaccup --setup`), a configuration wizard helps you define paths for your FLAC library, backup destination, database, and logs. It also sets an initial rescan frequency. This creates a `flaccup_config.ini` file.
2.  **Scanning:** When `flaccup` is run:
    * It scans your target FLAC library directory.
    * For each FLAC file, it checks its status in the local SQLite database.
    * If a file is new, or if its last scan date is older than the configured `RESCAN_DAYS_THRESHOLD`, a full scan is performed:
        * **Integrity Check:** `flac -t` is run.
        * **MD5 Checksum:** The audio MD5 is generated using `metaflac`. This new MD5 is compared against any previously stored MD5 to detect changes.
    * The database is updated with the latest scan results, MD5 checksum, and scan date.
3.  **Backup:** If a file passes the integrity check and its MD5 checksum is unchanged (or it's a new, healthy file), it is backed up to the backup destination using `rsync`.
4.  **Logging:** All actions, errors, and summaries are logged to a timestamped file in the configured log directory.
5.  **Scheduler (`Flaccup.scheduler`):** This separate utility helps manage the scan workload. When run (e.g., `python -m flaccup.scheduler --frequency weekly`), it:
    * Updates the `RESCAN_DAYS_THRESHOLD` in your `flaccup_config.ini` based on the chosen frequency.
    * Scans your library and database to ensure they are in sync (adds new files to DB, removes records of deleted files).
    * Evenly distributes the `last_scan_date` for all files in the database over the chosen frequency period. This ensures that the main `flaccup` command has a manageable number of files to process each time it's run, rather than all files becoming "due" for a re-scan on the same day.

## Requirements

### Python
* Python 3.7 or newer.

### External Command-Line Tools
Flaccup relies on the following external tools. These **must be installed and accessible in your system's PATH**:

* **`flac`**: For file integrity testing.
    * **Linux:** Usually available via package managers (e.g., `sudo apt install flac`).
    * **macOS:** Can be installed via Homebrew (e.g., `brew install flac`).
    * **Windows:** Download from the [official Xiph.org site](https://xiph.org/flac/download.html) or use a package manager like Chocolatey.
* **`metaflac`**: For reading FLAC metadata, notably the audio stream's MD5 sum. Typically bundled with `flac`.
* **`rsync`**: For file synchronization and backups.
    * **Linux & macOS:** Usually pre-installed or available via package managers.
    * **Windows:** `rsync` is not natively available. You can use it via:
        * **Windows Subsystem for Linux (WSL):** Install a Linux distribution from the Microsoft Store and then install `rsync` within WSL (e.g., `sudo apt install rsync`). You will need to ensure Flaccup can call WSL's `rsync` and that paths are handled correctly (e.g., `/mnt/c/...` for C: drive).
        * **Cygwin:** Install [Cygwin](https://www.cygwin.com/) and select the `rsync` package during installation.
        * Alternatively, pre-compiled `rsync` binaries for Windows (often bundled with cwRsync or similar packages) may work if added to your PATH.

`flaccup` includes checks for these commands.

## Installation

### From PyPI (Recommended)

`pip install flaccup`

### Managing Scan Frequency and Load (Scheduler)

The `flaccup.scheduler` module helps you manage how often files are re-scanned and ensures that the workload is spread out.

To run the scheduler, you run:

`flaccup.scheduler --frequency <frequency_choice>`

Replace "frequency_choice" with one of the following:

    daily: Sets RESCAN_DAYS_THRESHOLD to 1.
    weekly: Sets RESCAN_DAYS_THRESHOLD to 7.
    monthly: Sets RESCAN_DAYS_THRESHOLD to 30.
    yearly: Sets RESCAN_DAYS_THRESHOLD to 365.

### Contribution

Contributions are more than welcome! Feel free to submit a pull request or open issues on the GitHub repository!

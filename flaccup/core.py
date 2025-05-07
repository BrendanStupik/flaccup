import os
import subprocess
from datetime import datetime, timedelta
import sqlite3
import configparser
import sys
import traceback

try:
    from . import wizard
except ImportError:
    import wizard

APP_CONFIG = None
TARGET_DIRECTORY = None
BACKUP_DESTINATION_BASE = None
LOG_DIRECTORY = None
DATABASE_PATH = None
RESCAN_DAYS_THRESHOLD = None

def load_app_config(config_file_path_to_load):
    global APP_CONFIG, TARGET_DIRECTORY, BACKUP_DESTINATION_BASE, LOG_DIRECTORY, DATABASE_PATH, RESCAN_DAYS_THRESHOLD
    config = configparser.ConfigParser()
    if not os.path.exists(config_file_path_to_load):
        print(f"CRITICAL: Config file {config_file_path_to_load} not found by core.py. Please run setup.")
        sys.exit(1)
    config.read(config_file_path_to_load)
    cfg = {}
    try:
        cfg["DATABASE_PATH"] = config.get('General', 'database_path')
        cfg["LOG_DIRECTORY"] = config.get('General', 'log_directory')
        cfg["TARGET_DIRECTORY"] = config.get('General', 'target_directory')
        cfg["BACKUP_DESTINATION_BASE"] = config.get('General', 'backup_destination_base')
        cfg["RESCAN_DAYS_THRESHOLD"] = config.getint('Scanning', 'rescan_days_threshold')
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"CRITICAL: Missing or invalid configuration in {config_file_path_to_load}: {e}")
        sys.exit(1)
    APP_CONFIG = cfg
    TARGET_DIRECTORY = APP_CONFIG["TARGET_DIRECTORY"]
    BACKUP_DESTINATION_BASE = APP_CONFIG["BACKUP_DESTINATION_BASE"]
    LOG_DIRECTORY = APP_CONFIG["LOG_DIRECTORY"]
    DATABASE_PATH = APP_CONFIG["DATABASE_PATH"]
    RESCAN_DAYS_THRESHOLD = APP_CONFIG["RESCAN_DAYS_THRESHOLD"]
    print(f"Core configuration loaded from {config_file_path_to_load}:")
    print(f"  DB Path: {DATABASE_PATH}")
    print(f"  Target Dir: {TARGET_DIRECTORY}")
    print(f"  Rescan Threshold: {RESCAN_DAYS_THRESHOLD} days")

def initialize_database(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flac_file_data (
            file_path TEXT PRIMARY KEY,
            filename TEXT,
            directory TEXT,
            last_scan_date TEXT,
            integrity_status TEXT,
            current_md5_checksum TEXT,
            previous_md5_checksum TEXT,
            md5_match_status TEXT,
            last_successful_backup_date TEXT,
            last_seen_date TEXT,
            file_present_in_library INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_directory_flac_backup ON flac_file_data (directory)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_last_scan_date ON flac_file_data (last_scan_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_present ON flac_file_data (file_present_in_library)')
    conn.commit()
    return conn

def generate_audio_md5(file_path):
    try:
        result = subprocess.run(
            ["metaflac", "--show-md5sum", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            print(f"      MD5 Error: Failed to read audio MD5 from {os.path.basename(file_path)}. STDERR: {result.stderr.strip()}")
            return None
    except FileNotFoundError:
        print("      MD5 Error: 'metaflac' command not found.")
        raise
    except Exception as e:
        print(f"      MD5 Error: Exception generating audio MD5 for {os.path.basename(file_path)}: {e}")
        return None

def check_flac_integrity(file_path):
    try:
        process = subprocess.run(
            ["flac", "-t", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
        )
        stderr_lower = process.stderr.lower()
        stdout_lower = process.stdout.lower()
        if "ok" in stderr_lower or "ok" in stdout_lower:
            return 'ok'
        elif "error" in stderr_lower or "state" in stderr_lower or \
             "error" in stdout_lower or "state" in stdout_lower :
            print(f"      FLAC Test: Corruption detected in {os.path.basename(file_path)}. STDERR: {process.stderr.strip()}, STDOUT: {process.stdout.strip()}")
            return 'corrupted_flac_t'
        elif process.returncode != 0 :
             print(f"      FLAC Test: Command execution failed for {os.path.basename(file_path)} (ret: {process.returncode}). STDERR: {process.stderr.strip()}, STDOUT: {process.stdout.strip()}")
             return 'error_flac_t_execution'
        else:
            print(f"      FLAC Test: Ambiguous result for {os.path.basename(file_path)} (ret: {process.returncode}). STDERR: {process.stderr.strip()}, STDOUT: {process.stdout.strip()}")
            return 'corrupted_flac_t_unknown'
    except FileNotFoundError:
        print("      FLAC Test Error: 'flac' command not found.")
        return 'error_flac_cmd_not_found'
    except Exception as e:
        print(f"      FLAC Test Error: Exception during 'flac -t' for {os.path.basename(file_path)}: {e}")
        return 'error_flac_exception'

def verify_and_backup_flac_files():
    if not APP_CONFIG:
        print("CRITICAL: Application configuration not loaded in core.py. Exiting.")
        sys.exit(1)
    os.makedirs(LOG_DIRECTORY, exist_ok=True)
    current_run_timestamp_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
    log_file_path = os.path.join(LOG_DIRECTORY, f"flac_backup_audit_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
    conn = initialize_database(DATABASE_PATH)
    cursor = conn.cursor()
    stats = {
        "files_iterated": 0, "newly_added_to_db": 0, "backed_up": 0,
        "integrity_failed": 0, "md5_mismatched": 0, "md5_error": 0,
        "full_scans_performed": 0, "full_scans_skipped_due_to_recency": 0,
        "rsync_errors": 0, "flac_cmd_errors": 0,
        "metaflac_cmd_errors": 0, "other_errors": 0, "missing_deleted_marked": 0
    }
    print(f"Starting run: {current_run_timestamp_iso}")
    print(f"Target: {TARGET_DIRECTORY}, Backup Base: {BACKUP_DESTINATION_BASE}, DB: {DATABASE_PATH}")
    print(f"Rescan if older than {RESCAN_DAYS_THRESHOLD} days. All due files will be processed.")
    rescan_threshold_datetime = datetime.now() - timedelta(days=RESCAN_DAYS_THRESHOLD)
    paths_found_in_current_scan = set()
    print(f"\nScanning files in {TARGET_DIRECTORY}...")
    for root, _, files_in_dir in os.walk(TARGET_DIRECTORY):
        for file_name in files_in_dir:
            if not file_name.lower().endswith('.flac'):
                continue
            stats["files_iterated"] += 1
            file_path = os.path.join(root, file_name)
            paths_found_in_current_scan.add(file_path)
            relative_file_path = os.path.relpath(file_path, TARGET_DIRECTORY)
            file_basename = os.path.basename(file_path)
            file_dirname = os.path.dirname(file_path)
            if stats["files_iterated"] % 200 == 0:
                print(f"  Iterated {stats['files_iterated']} files...")
            cursor.execute('''
                SELECT last_scan_date, integrity_status, current_md5_checksum,
                       previous_md5_checksum, md5_match_status,
                       last_successful_backup_date, file_present_in_library
                FROM flac_file_data WHERE file_path = ?
            ''', (file_path,))
            db_record = cursor.fetchone()
            db_last_scan_date_str = db_record[0] if db_record else None
            db_integrity_status = db_record[1] if db_record else 'new_file'
            db_current_md5 = db_record[2] if db_record else None
            db_previous_md5 = db_record[3] if db_record else None
            db_md5_match_status = db_record[4] if db_record else 'not_checked'
            current_file_integrity_status = db_integrity_status
            current_file_md5 = db_current_md5
            current_file_md5_match_status = db_md5_match_status
            scan_time_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
            new_db_entry = not bool(db_record)
            perform_full_scan = False
            if new_db_entry:
                stats["newly_added_to_db"] +=1
                print(f"\n  New file detected: {relative_file_path}")
                perform_full_scan = True
                db_last_scan_date_str = (datetime.now() - timedelta(days=RESCAN_DAYS_THRESHOLD + 90)).isoformat(sep=' ', timespec='seconds')
                current_file_integrity_status = 'pending_scan'
                current_file_md5_match_status = 'not_checked'
            else:
                if db_last_scan_date_str:
                    try:
                        last_scan_datetime_obj = datetime.fromisoformat(db_last_scan_date_str)
                        if last_scan_datetime_obj <= rescan_threshold_datetime:
                            perform_full_scan = True
                        else:
                            stats["full_scans_skipped_due_to_recency"] += 1
                    except ValueError:
                        print(f"  Warning: Invalid last_scan_date '{db_last_scan_date_str}' in DB for {relative_file_path}. Will perform rescan.")
                        perform_full_scan = True
                else:
                    perform_full_scan = True
            if perform_full_scan:
                stats["full_scans_performed"] += 1
                print(f"  Performing full scan for: {relative_file_path}")
                try:
                    current_file_integrity_status = check_flac_integrity(file_path)
                    if current_file_integrity_status.startswith('error_flac_cmd_not_found'): stats["flac_cmd_errors"] +=1
                    elif current_file_integrity_status.startswith('error_'): stats["other_errors"] +=1
                except Exception as e:
                    current_file_integrity_status = 'error_flac_exception'
                    stats["other_errors"] +=1
                    print(f"    Unexpected error during flac integrity check: {e}")
                if current_file_integrity_status != 'ok':
                    print(f"    FLAC test result: {current_file_integrity_status}")
                    stats["integrity_failed"] +=1
                else:
                    print(f"    FLAC test result: ok")
                newly_generated_md5 = None
                if not current_file_integrity_status.startswith('error_flac_cmd_not_found'):
                    try:
                        newly_generated_md5 = generate_audio_md5(file_path)
                    except FileNotFoundError:
                        current_file_md5_match_status = 'error_md5_metaflac_cmd_not_found'
                        stats["metaflac_cmd_errors"] +=1
                    except Exception as e:
                        current_file_md5_match_status = 'error_md5_generation'
                        stats["md5_error"] += 1
                        print(f"    Unexpected error during MD5 generation: {e}")
                else:
                     current_file_md5_match_status = 'error_md5_skipped_due_to_flac_error'
                if newly_generated_md5:
                    current_file_md5 = newly_generated_md5
                    if db_current_md5:
                        if newly_generated_md5 == db_current_md5:
                            current_file_md5_match_status = 'matched'
                        else:
                            current_file_md5_match_status = 'mismatched'
                            stats["md5_mismatched"] +=1
                            print(f"    MD5 MISMATCH! Path: {relative_file_path}, DB: {db_current_md5}, New: {newly_generated_md5}")
                    else:
                        current_file_md5_match_status = 'new_file_md5' if new_db_entry else 'first_valid_md5_scan'
                elif not current_file_md5_match_status.startswith('error_md5_'):
                    current_file_md5_match_status = 'error_md5_generation'
                    stats["md5_error"] += 1
                print(f"    MD5 status: {current_file_md5_match_status}, Current Audio MD5: {current_file_md5}")
                effective_scan_date_for_db = scan_time_iso
            else:
                effective_scan_date_for_db = db_last_scan_date_str if db_last_scan_date_str else current_run_timestamp_iso
            if new_db_entry:
                 cursor.execute('''
                    INSERT INTO flac_file_data (
                        file_path, filename, directory, last_scan_date,
                        integrity_status, current_md5_checksum, previous_md5_checksum, md5_match_status,
                        last_seen_date, file_present_in_library
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ''', (file_path, file_basename, file_dirname,
                      effective_scan_date_for_db,
                      current_file_integrity_status, current_file_md5, None, current_file_md5_match_status,
                      current_run_timestamp_iso))
            else:
                effective_previous_md5_for_update = db_current_md5 if perform_full_scan and newly_generated_md5 and db_current_md5 != newly_generated_md5 else db_previous_md5
                cursor.execute('''
                    UPDATE flac_file_data
                    SET last_scan_date = ?, integrity_status = ?,
                        current_md5_checksum = ?, previous_md5_checksum = ?, md5_match_status = ?,
                        last_seen_date = ?, file_present_in_library = 1,
                        filename = ?, directory = ?
                    WHERE file_path = ?
                ''', (effective_scan_date_for_db, current_file_integrity_status,
                      current_file_md5, effective_previous_md5_for_update, current_file_md5_match_status,
                      current_run_timestamp_iso,
                      file_basename, file_dirname, file_path))

            if perform_full_scan:
                is_healthy_for_backup = (current_file_integrity_status == 'ok') and \
                                        (current_file_md5_match_status in ['matched', 'new_file_md5', 'first_valid_md5_scan', 'no_previous_md5'])
            else:
                is_healthy_for_backup = False

            if is_healthy_for_backup:
                backup_file_dest_path = os.path.join(BACKUP_DESTINATION_BASE, relative_file_path)
                backup_file_dest_dir = os.path.dirname(backup_file_dest_path)
                os.makedirs(backup_file_dest_dir, exist_ok=True)
                try:
                    rsync_process = subprocess.run(
                        ["rsync", "-a", "--checksum", file_path, backup_file_dest_path],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    stats["backed_up"] += 1
                    backup_time_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
                    cursor.execute('UPDATE flac_file_data SET last_successful_backup_date = ? WHERE file_path = ?', (backup_time_iso, file_path))
                except subprocess.CalledProcessError as e:
                    stats["rsync_errors"] += 1
                    print(f"    RSYNC ERROR for {relative_file_path}: {e.stderr or e.stdout or e}")
                except FileNotFoundError:
                     stats["rsync_errors"] += 1
                     print("    RSYNC ERROR: 'rsync' command not found. Cannot backup.")
            conn.commit()

    print("\nChecking for missing/deleted files (in DB but not found in scan)...")
    cursor.execute("SELECT file_path FROM flac_file_data WHERE file_present_in_library = 1")
    db_present_files_paths = {row[0] for row in cursor.fetchall()}
    missing_files_paths = db_present_files_paths - paths_found_in_current_scan
    if missing_files_paths:
        for missing_path in missing_files_paths:
            stats["missing_deleted_marked"] += 1
            cursor.execute("UPDATE flac_file_data SET file_present_in_library = 0, last_seen_date = ? WHERE file_path = ?",
                           (current_run_timestamp_iso, missing_path))
        conn.commit()
    print(f"  Found and marked {stats['missing_deleted_marked']} missing/deleted files in DB.")
    print(f"\nSaving log file to: {log_file_path}")
    with open(log_file_path, "w") as log_f:
        log_f.write(f"FLAC Backup Utility Log - Run at: {current_run_timestamp_iso}\n")
        log_f.write(f"Target Directory: {TARGET_DIRECTORY}\n")
        log_f.write(f"Backup Destination Base: {BACKUP_DESTINATION_BASE}\n")
        log_f.write(f"Database: {DATABASE_PATH}\n")
        log_f.write(f"Config: RESCAN_DAYS_THRESHOLD={RESCAN_DAYS_THRESHOLD}\n")
        log_f.write("=" * 40 + "\n\n")
        log_f.write("==== SUMMARY ====\n")
        for key, value in stats.items():
            log_f.write(f"{key.replace('_', ' ').capitalize():<40}: {value}\n")
        log_f.write("\n" + "=" * 40 + "\n")
        issues_queries = {
            "FILES FAILED FLAC INTEGRITY (`flac -t`)": "SELECT file_path, integrity_status FROM flac_file_data WHERE integrity_status NOT LIKE 'ok' AND integrity_status NOT LIKE '%error%' AND integrity_status NOT LIKE 'pending_scan' AND file_present_in_library = 1 ORDER BY file_path",
            "FILES WITH AUDIO MD5 MISMATCH": "SELECT file_path, previous_md5_checksum, current_md5_checksum FROM flac_file_data WHERE md5_match_status = 'mismatched' AND file_present_in_library = 1 ORDER BY file_path",
            "FILES WITH MD5 ERRORS (generation/metaflac)": "SELECT file_path, md5_match_status FROM flac_file_data WHERE md5_match_status LIKE '%error%' AND file_present_in_library = 1 ORDER BY file_path",
            "FILES WITH FLAC COMMAND/EXECUTION ERRORS": "SELECT file_path, integrity_status FROM flac_file_data WHERE integrity_status LIKE '%error%' AND file_present_in_library = 1 ORDER BY file_path",
            "RSYNC ERRORS (check console output for details)": None,
            "MISSING/DELETED FILES (marked in DB this run)": f"SELECT file_path FROM flac_file_data WHERE file_present_in_library = 0 AND last_seen_date = '{current_run_timestamp_iso}' ORDER BY file_path"
        }
        for title, query in issues_queries.items():
            if query:
                log_f.write(f"\n==== {title} ====\n")
                try:
                    cursor.execute(query)
                    results = cursor.fetchall()
                    if results:
                        for row in results: log_f.write(f"  {', '.join(map(str,row))}\n")
                    else: log_f.write("  None found.\n")
                except sqlite3.Error as e:
                    log_f.write(f"  Error executing query for '{title}': {e}\n")
            elif title.startswith("RSYNC ERRORS") and stats.get("rsync_errors", 0) > 0 :
                 log_f.write(f"\n==== {title} ====\n")
                 log_f.write(f"  {stats.get('rsync_errors',0)} instances. See console for paths.\n")
    conn.close()
    print("\n" + "="*20 + " AUDIT AND BACKUP COMPLETE " + "="*20)
    for key, value in stats.items():
        print(f"{key.replace('_', ' ').capitalize():<40}: {value}")
    print(f"Log file saved at: {log_file_path}")

def main_cli():
    config_file_to_use = wizard.get_config_file_path()
    if not config_file_to_use or not os.path.exists(config_file_to_use):
        print("Configuration file not found or setup not completed. Attempting to run wizard...")
        config_file_to_use = wizard.ensure_config_exists()
        if not config_file_to_use:
            print("Setup wizard failed or was aborted. Exiting Flaccup core.")
            sys.exit(1)
    load_app_config(config_file_to_use)
    print(f"Starting FLAC Backup Utility (core using: {config_file_to_use})...")
    missing_cmds = []
    for cmd_test in [["flac", "--version"], ["metaflac", "--version"], ["rsync", "--version"]]:
        try:
            subprocess.run(cmd_test, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            missing_cmds.append(cmd_test[0])
        except subprocess.CalledProcessError as e:
            print(f"Warning: Command '{cmd_test[0]}' exists but version check failed: {e.stderr or e.stdout}")
    if missing_cmds:
        print(f"ERROR: Required command(s) not found: {', '.join(missing_cmds)}. Please install and ensure they are in your PATH.")
        sys.exit(1)
    try:
        verify_and_backup_flac_files()
    except Exception as e:
        print(f"CRITICAL ERROR during script execution: {e}")
        traceback.print_exc()
        sys.exit(1)
    print("FLAC Backup Utility (core) process finished.")

if __name__ == "__main__":
    main_cli()

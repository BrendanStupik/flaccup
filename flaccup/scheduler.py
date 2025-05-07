import sqlite3
from datetime import datetime, timedelta
import argparse
import sys
import os
import configparser
import math

try:
    from . import wizard
except ImportError:
    import wizard


DB_CONFIG_SECTION = "General"
DB_CONFIG_OPTION = "database_path"
TARGET_DIR_OPTION = "target_directory"
SCAN_CONFIG_SECTION = "Scanning"
SCAN_CONFIG_OPTION = "rescan_days_threshold"

TABLE_NAME_DEFAULT = "flac_file_data"
PRIMARY_KEY_COLUMN_DEFAULT = "file_path"

def get_threshold_for_frequency(frequency_arg):
    if frequency_arg == "daily":
        return 1
    elif frequency_arg == "weekly":
        return 7
    elif frequency_arg == "monthly":
        return 30
    elif frequency_arg == "yearly":
        return 365
    else:
        print(f"Error: Unknown frequency '{frequency_arg}' for threshold calculation.")
        sys.exit(1)

def update_rescan_threshold_in_config(config_file_path, new_threshold):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file_path):
        print(f"Error: Config file {config_file_path} not found. Cannot update threshold. Run 'flaccup --setup'.")
        sys.exit(1)

    config.read(config_file_path)

    if not config.has_section(SCAN_CONFIG_SECTION):
        config.add_section(SCAN_CONFIG_SECTION)
        print(f"Added section [{SCAN_CONFIG_SECTION}] to config.")

    config.set(SCAN_CONFIG_SECTION, SCAN_CONFIG_OPTION, str(new_threshold))

    try:
        with open(config_file_path, 'w') as configfile:
            config.write(configfile)
        print(f"Successfully updated '{SCAN_CONFIG_OPTION}' in '{config_file_path}' to: {new_threshold} days.")
    except IOError as e:
        print(f"Error writing updated config file {config_file_path}: {e}")
        sys.exit(1)

def load_paths_from_config(config_file_path):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file_path):
         print(f"Error: Config file {config_file_path} not found. Cannot load paths. Run 'flaccup --setup'.")
         sys.exit(1)
    config.read(config_file_path)
    paths = {}
    try:
        paths["db_path"] = config.get(DB_CONFIG_SECTION, DB_CONFIG_OPTION)
        paths["target_dir"] = config.get(DB_CONFIG_SECTION, TARGET_DIR_OPTION)
        return paths
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"Error: Could not read database or target path from config file {config_file_path}: {e}")
        print(f"Please ensure the config file has [{DB_CONFIG_SECTION}] section with {DB_CONFIG_OPTION} and {TARGET_DIR_OPTION} options.")
        sys.exit(1)


def reschedule_and_populate(db_path, target_dir, frequency_arg, table_name, pk_column, effective_threshold_days):
    print(f"Scheduler starting...")
    print(f"Scanning target directory: {target_dir}")

    disk_files = set()
    files_iterated_for_scan = 0
    for root, _, files_in_dir in os.walk(target_dir):
        for file_name in files_in_dir:
            if not file_name.lower().endswith('.flac'):
                continue
            files_iterated_for_scan += 1
            file_path = os.path.join(root, file_name)
            disk_files.add(file_path)
            if files_iterated_for_scan % 500 == 0:
                print(f"  Scanned {files_iterated_for_scan} files on disk...")
    print(f"Found {len(disk_files)} '.flac' files on disk.")

    print(f"Connecting to database: {db_path}")
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {table_name} (
                file_path TEXT PRIMARY KEY, filename TEXT, directory TEXT, last_scan_date TEXT,
                integrity_status TEXT, current_md5_checksum TEXT, previous_md5_checksum TEXT,
                md5_match_status TEXT, last_successful_backup_date TEXT, last_seen_date TEXT,
                file_present_in_library INTEGER DEFAULT 1 ) ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error connecting to or ensuring table exists in database: {e}")
        if conn: conn.close()
        sys.exit(1)

    db_all_files_paths = set()
    try:
        cursor.execute(f"SELECT {pk_column} FROM {table_name}")
        db_all_files_paths = {row[0] for row in cursor.fetchall()}
        print(f"Found {len(db_all_files_paths)} total records in database.")
    except sqlite3.Error as e:
        print(f"Warning: Error fetching existing file paths from table '{table_name}': {e}")

    new_files_on_disk = disk_files - db_all_files_paths
    missing_files_in_db = db_all_files_paths - disk_files

    deleted_count = 0
    if missing_files_in_db:
        print(f"Found {len(missing_files_in_db)} files in DB missing from disk. Removing from DB...")
        try:
            chunk_size = 500
            missing_files_list = list(missing_files_in_db)
            for i in range(0, len(missing_files_list), chunk_size):
                chunk = missing_files_list[i:i + chunk_size]
                placeholders = ','.join('?' * len(chunk))
                delete_sql = f"DELETE FROM {table_name} WHERE {pk_column} IN ({placeholders})"
                cursor.execute(delete_sql, tuple(chunk))
                deleted_count += len(chunk)
                print(f"  Deleting chunk {i // chunk_size + 1}...")
                for item in chunk[:5]: print(f"    - {item}")
                if len(chunk)>5: print("    ...")
            conn.commit()
            print(f"Removed {deleted_count} missing file records from the database.")
        except sqlite3.Error as e:
            print(f"Error deleting missing files from database: {e}")
            conn.rollback()
    else:
        print("No files found missing from disk.")

    added_count = 0
    if new_files_on_disk:
        print(f"Found {len(new_files_on_disk)} new files on disk to add to the database.")
        current_time_iso = datetime.now().isoformat(sep=' ', timespec='seconds')
        insert_sql = f''' INSERT INTO {table_name} (
                              file_path, filename, directory, integrity_status,
                              md5_match_status, last_seen_date, file_present_in_library, last_scan_date
                          ) VALUES (?, ?, ?, ?, ?, ?, 1, NULL) '''

        new_files_data = []
        for file_path in new_files_on_disk:
            new_files_data.append((
                file_path,
                os.path.basename(file_path),
                os.path.dirname(file_path),
                'pending_scan',
                'not_checked',
                current_time_iso
            ))

        try:
            cursor.executemany(insert_sql, new_files_data)
            conn.commit()
            added_count = len(new_files_data)
            print(f"Added {added_count} new files to the database.")
        except sqlite3.Error as e:
            print(f"Error adding new files to database: {e}")
            conn.rollback()
    else:
         print("No new files found on disk to add.")

    files_to_schedule_pks = []
    try:
        if not disk_files:
             print("No files on disk to schedule.")
        else:
            placeholders = ','.join('?' * len(disk_files))
            sql_fetch_pks = f"SELECT {pk_column} FROM {table_name} WHERE {pk_column} IN ({placeholders})"
            cursor.execute(sql_fetch_pks, tuple(disk_files))
            files_to_schedule_pks = [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
         print(f"Error fetching primary keys for files to schedule: {e}")
         conn.close()
         sys.exit(1)

    num_entries = len(files_to_schedule_pks)
    if num_entries == 0:
        print("No entries found to schedule dates for.")
        conn.close()
        return

    print(f"\nRescheduling {num_entries} present files with new threshold {effective_threshold_days} days.")
    print(f"Goal: Distribute their next scan over the next ~{effective_threshold_days} days.")

    distribution_period_days = effective_threshold_days

    if distribution_period_days <= 0:
        print("Zero or negative distribution period, cannot schedule.")
        conn.close()
        return

    entries_per_day_slot = math.ceil(num_entries / distribution_period_days)
    if entries_per_day_slot == 0 : entries_per_day_slot = 1

    print(f"Distributing {num_entries} entries over {distribution_period_days} future 'due' day slots.")
    print(f"Approx. {entries_per_day_slot} entries will be set to become due per day slot.")

    scheduler_run_date = datetime.now()
    updated_count = 0
    error_count = 0

    for i, pk_value in enumerate(files_to_schedule_pks):
        slot_index = i // entries_per_day_slot
        slot_index = min(slot_index, distribution_period_days - 1)

        target_processing_date = scheduler_run_date.replace(hour=1, minute=0, second=0, microsecond=0) + \
                                 timedelta(days=slot_index)

        new_last_scan_date_for_db = target_processing_date - \
                                    timedelta(days=effective_threshold_days + 1)

        new_date_str = new_last_scan_date_for_db.strftime("%Y-%m-%d %H:%M:%S")

        try:
            cursor.execute(f"UPDATE {table_name} SET last_scan_date = ?, file_present_in_library = 1 WHERE {pk_column} = ?", (new_date_str, pk_value))
            updated_count +=1
        except sqlite3.Error as e:
            print(f"Error updating entry PK {str(pk_value)[:50]}... date to {new_date_str}: {e}")
            error_count +=1

        if (updated_count > 0 and updated_count % 1000 == 0) or i == num_entries -1 :
            print(f"  Scheduled {updated_count}/{num_entries} entries...")
            if i < 5 or i > num_entries - 5 :
                 print(f"    Entry PK {str(pk_value)[:20]}... -> Slot {slot_index}, Target Due {target_processing_date.strftime('%Y-%m-%d')}, DB Date {new_date_str}")

    try:
        conn.commit()
        print(f"\nCommitted date updates to the database.")
        print(f"Successfully updated {updated_count} file dates.")
        if error_count > 0:
            print(f"Failed to update dates for {error_count} entries.")
    except sqlite3.Error as e:
        print(f"Error committing date changes: {e}")
    finally:
        if conn: conn.close()

    print(f"\nScheduler finished. Flaccup Core (threshold={effective_threshold_days}) should now process files spread over the '{frequency_arg}' period.")


def main_cli():
    parser = argparse.ArgumentParser(
        description="Scans target directory, adds/removes files in DB to match disk, updates RESCAN_DAYS_THRESHOLD in config, "
                    "and reschedules *all* present files in the database to align with the new threshold "
                    "and chosen frequency, distributing their 'due dates' over the period."
    )
    parser.add_argument(
        "-f", "--frequency",
        choices=["daily", "weekly", "monthly", "yearly"],
        required=True,
        help="Set the desired scan frequency. This will update the rescan threshold in the config file "
             "and redistribute last_scan_dates for all present files."
    )
    parser.add_argument(
        "--table-name",
        default=TABLE_NAME_DEFAULT,
        help=f"Name of the table to manage. Default: {TABLE_NAME_DEFAULT}"
    )
    parser.add_argument(
        "--pk-column",
        default=PRIMARY_KEY_COLUMN_DEFAULT,
        help=f"Name of the primary key column (must be file path for this script). Default: {PRIMARY_KEY_COLUMN_DEFAULT}"
    )

    args = parser.parse_args()

    if args.pk_column != 'file_path':
         print("Error: This script currently requires the primary key column to be 'file_path'.")
         sys.exit(1)

    config_file_path = wizard.get_config_file_path()
    if not os.path.exists(config_file_path):
         print(f"Error: Config file {config_file_path} not found. Run 'flaccup --setup' first.")
         sys.exit(1)

    new_threshold = get_threshold_for_frequency(args.frequency)
    print(f"Selected frequency: {args.frequency}. Corresponding rescan threshold: {new_threshold} days.")
    update_rescan_threshold_in_config(config_file_path, new_threshold)

    paths = load_paths_from_config(config_file_path)
    effective_db_path = paths["db_path"]
    effective_target_dir = paths["target_dir"]

    if not os.path.isdir(effective_target_dir):
        print(f"Error: Target directory specified in config does not exist: {effective_target_dir}")
        sys.exit(1)

    reschedule_and_populate(
        effective_db_path,
        effective_target_dir,
        args.frequency,
        args.table_name,
        args.pk_column,
        new_threshold
    )

if __name__ == "__main__":
    main_cli()

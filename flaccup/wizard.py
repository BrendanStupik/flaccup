import os
import sys
import configparser
from pathlib import Path
import traceback

APP_NAME = "flaccup"
APP_AUTHOR = "flaccup"
CONFIG_FILE_NAME = "flaccup_config.ini"

try:
    from . import scheduler as scheduler_module
except ImportError:
    import scheduler as scheduler_module


def get_default_config_dir():
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_AUTHOR / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME

def get_config_file_path():
    return get_default_config_dir() / CONFIG_FILE_NAME

def run_setup_wizard():
    print("--- Flaccup Setup Wizard ---")

    default_config_dir = get_default_config_dir()
    print(f"\nThe configuration file will store paths and settings for Flaccup.")
    config_dir_str = input(f"Enter config directory path [{default_config_dir}]: ") or str(default_config_dir)
    config_dir = Path(config_dir_str)

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        print(f"Using configuration directory: {config_dir}")
    except OSError as e:
        print(f"Error: Could not create configuration directory {config_dir}: {e}")
        return None

    config_file_path = config_dir / CONFIG_FILE_NAME

    print("\nPlease provide the following paths:")

    default_db_path = config_dir / "flac_backup_utility.db"
    db_path_str = input(f"Database file path [{default_db_path}]: ") or str(default_db_path)

    target_dir_str = ""
    while not target_dir_str:
         target_dir_str = input("Path to your FLAC library (TARGET_DIRECTORY): ")
         if not target_dir_str: print("This path cannot be empty.")

    backup_dest_str = ""
    while not backup_dest_str:
        backup_dest_str = input("Path to your backup destination (BACKUP_DESTINATION_BASE): ")
        if not backup_dest_str: print("This path cannot be empty.")

    default_log_dir = config_dir / "logs"
    log_dir_str = input(f"Log directory path [{default_log_dir}]: ") or str(default_log_dir)

    initial_threshold_str = input("Initial RESCAN_DAYS_THRESHOLD (e.g., 1=daily, 7=weekly, 30=monthly) [7]: ") or "7"
    initial_threshold = 7
    try:
        initial_threshold = int(initial_threshold_str)
        if initial_threshold <= 0:
            print("Rescan threshold must be a positive number. Using 7.")
            initial_threshold = 7
    except ValueError:
        print("Invalid number for threshold. Using 7.")
        initial_threshold = 7

    config = configparser.ConfigParser()
    config["General"] = {
        "database_path": db_path_str,
        "log_directory": log_dir_str,
        "target_directory": target_dir_str,
        "backup_destination_base": backup_dest_str,
    }
    config["Scanning"] = {
        "rescan_days_threshold": str(initial_threshold)
    }

    config_file_written = False
    try:
        with open(config_file_path, 'w') as configfile:
            config.write(configfile)
        print(f"\nConfiguration saved to: {config_file_path}")
        config_file_written = True
    except IOError as e:
        print(f"Error: Could not write configuration file {config_file_path}: {e}")
        return None

    final_config_path = str(config_file_path)

    if config_file_written:
        print("\nRunning initial directory scan and scheduling...")
        print("(This might take a while depending on your library size)")

        try:
            frequency_map = {1: "daily", 7: "weekly", 30: "monthly", 365: "yearly"}
            initial_frequency = frequency_map.get(initial_threshold)

            if not initial_frequency:
                 print(f"Warning: Threshold {initial_threshold} doesn't map directly to standard frequency. Using custom logic if available or defaulting.")
                 if initial_threshold <= 1: initial_frequency = "daily"
                 elif initial_threshold <= 7: initial_frequency = "weekly"
                 elif initial_threshold <= 30: initial_frequency = "monthly"
                 else: initial_frequency = "yearly"
                 print(f"Using frequency logic: '{initial_frequency}' for initial scheduling pattern.")


            scheduler_module.reschedule_and_populate(
                db_path=db_path_str,
                target_dir=target_dir_str,
                frequency_arg=initial_frequency,
                table_name=scheduler_module.TABLE_NAME_DEFAULT,
                pk_column=scheduler_module.PRIMARY_KEY_COLUMN_DEFAULT,
                effective_threshold_days=initial_threshold
            )
            print("\nInitial scheduling complete.")
            print("Setup complete! You can now run flaccup normally.")

        except Exception as e:
            print("\n--- Error during initial scheduling ---")
            print(f"An error occurred: {e}")
            print("Configuration file was saved, but the initial scan/schedule failed.")
            print("You may need to run the scheduler manually (e.g., python -m flaccup.scheduler --frequency monthly) or check permissions/paths.")
            traceback.print_exc()

    return final_config_path

def ensure_config_exists():
    config_path = get_config_file_path()
    if not config_path.exists():
        print(f"Configuration file not found at {config_path}.")
        print("Running setup wizard...")
        return run_setup_wizard()
    return str(config_path)

if __name__ == '__main__':
    run_setup_wizard()

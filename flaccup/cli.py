import argparse
import sys

try:
    from . import wizard
    from . import core
except ImportError:
    import wizard
    import core

def main():
    parser = argparse.ArgumentParser(
        description="Flaccup: FLAC Integrity Checker and Backup Utility.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the interactive setup wizard to configure flaccup."
    )

    args = parser.parse_args()

    if args.setup:
        wizard.run_setup_wizard()
        sys.exit(0)

    config_file_actual_path = wizard.ensure_config_exists()

    if not config_file_actual_path:
        print("flaccup is not configured. Please run the setup wizard using --setup.")
        sys.exit(1)

    print(f"Using configuration file: {config_file_actual_path}")

    try:
        core.main_cli()
    except Exception as e:
        print(f"An error occurred during flaccup execution: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

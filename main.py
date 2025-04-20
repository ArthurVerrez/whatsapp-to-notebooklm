import argparse
import os
import utils
import logging

# Configure logging for the main script (optional, if utils doesn't cover everything)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(
        description="Parse a WhatsApp chat export file and convert it into multiple Markdown files suitable for NotebookLM, grouped by time period."
    )

    parser.add_argument(
        "file_path",
        type=str,
        help="Path to the WhatsApp export file (.txt)."
    )
    parser.add_argument(
        "conversation_name",
        type=str,
        help="A descriptive name for the conversation (used in Markdown titles)."
    )
    parser.add_argument(
        "-o", "--output-folder",
        type=str,
        default="output",
        help="Path to the folder where the output Markdown files will be saved. Defaults to 'output'."
    )
    parser.add_argument(
        "-t", "--time-group",
        type=str,
        default="AUTO",
        choices=utils.VALID_TIME_GROUPS, # Use the valid groups defined in utils
        help="Time period to group messages by. 'AUTO' determines the best fit based on MAX_FILES. Defaults to 'AUTO'."
    )

    args = parser.parse_args()

    # Basic validation for input file existence
    if not os.path.isfile(args.file_path):
        logging.error(f"Input file not found: {args.file_path}")
        parser.print_help()
        return # Exit if file doesn't exist

    logging.info(f"Input file: {args.file_path}")
    logging.info(f"Conversation name: {args.conversation_name}")
    logging.info(f"Output folder: {args.output_folder}")
    logging.info(f"Time grouping: {args.time_group}")

    try:
        utils.create_notebook_lm_files(
            file_path=args.file_path,
            conversation_name=args.conversation_name,
            save_folder_path=args.output_folder,
            time_group=args.time_group.upper() # Ensure uppercase for consistency
        )
        logging.info("Processing complete.")
    except FileNotFoundError:
        # Error should already be logged by utils.parse_whatsapp
        logging.error("Exiting due to file not found error during processing.")
    except (ValueError, IOError) as e:
        # Errors related to invalid args or file operations logged by utils
        logging.error(f"Exiting due to an error: {e}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}") # Log stack trace for unexpected errors

if __name__ == "__main__":
    main() 
"""Utilities for parsing WhatsApp chat exports and converting them to NotebookLM format."""

import re
from datetime import datetime
from typing import Dict, List, Literal, Tuple
import pandas as pd
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
MAX_FILES = 400 # Maximum number of output files allowed for AUTO grouping

# Regex to capture the date, time, sender, and first line of content
# Handles DD/MM/YY or D/M/YY date formats and HH:MM time format
WHATSAPP_PATTERN = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}), (?P<time>\d{1,2}:\d{2}) - (?P<sender>[^:]+): (?P<content>.*)"
)

def _parse_datetime_string(date_str: str, time_str: str) -> datetime:
    """
    Parses date and time strings into a datetime object.

    Assumes date format DD/MM/YY. Handles potential ambiguity by assuming
    years < 69 are 20xx and years >= 69 are 19xx. This follows the
    datetime.strptime %y behavior.

    Args:
        date_str: The date string (e.g., "25/12/23").
        time_str: The time string (e.g., "14:30").

    Returns:
        A datetime object.

    Raises:
        ValueError: If the date/time format is incorrect.
    """
    # Use %y for automatic handling of 2-digit years (00-68 -> 20xx, 69-99 -> 19xx)
    # Although WhatsApp typically uses DD/MM/YY, strptime expects MM/DD/YY or DD/MM/YY depending on locale,
    # so we specify the format explicitly.
    # Let's assume DD/MM/YY based on common WhatsApp usage. Adjust if your exports differ.
    datetime_str = f"{date_str} {time_str}"
    try:
        # Try DD/MM/YY first
        return datetime.strptime(datetime_str, "%d/%m/%y %H:%M")
    except ValueError:
        # If YY fails, try with YYYY
        return datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")


def parse_whatsapp(file_path: str) -> pd.DataFrame | None:
    """
    Parse a WhatsApp export file (.txt) into a Pandas DataFrame.

    Handles multiline messages and identifies media omissions.

    Args:
        file_path: Path to the WhatsApp export file.

    Returns:
        Pandas DataFrame with columns: 'datetime', 'sender', 'is_media', 'content'.
        Returns None if the file cannot be read or parsed.

    Raises:
        FileNotFoundError: If the file_path does not exist.
        ValueError: If the date/time format in a message is unexpected.
    """
    messages: List[Dict[str, str | datetime | bool]] = []
    current_message: Dict[str, str | datetime | bool] | None = None

    logging.info(f"Attempting to parse WhatsApp export file: {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()  # Remove leading/trailing whitespace
                if not line:
                    continue # Skip empty lines

                match = WHATSAPP_PATTERN.match(line)
                if match:
                    # If a new message starts, save the previous one (if exists)
                    if current_message:
                        # Finalize content processing for the previous message
                        current_message["content"] = "\n".join(current_message["content_lines"])
                        current_message["is_media"] = "<Media omitted>" in current_message["content"]
                        del current_message["content_lines"] # Remove temporary field
                        messages.append(current_message)

                    # Start a new message
                    msg_data = match.groupdict()
                    try:
                        dt = _parse_datetime_string(msg_data["date"], msg_data["time"])
                    except ValueError as e:
                         logging.error(f"Could not parse date/time in line: '{line}'. Error: {e}")
                         # Option 1: Skip this message
                         # current_message = None
                         # continue
                         # Option 2: Raise the error to stop processing
                         raise ValueError(f"Could not parse date/time in line: '{line}'") from e
                         # Option 3: Use a placeholder date (less recommended)
                         # dt = datetime.min

                    current_message = {
                        "datetime": dt,
                        "sender": msg_data["sender"],
                        "content_lines": [msg_data["content"].strip()], # Store lines temporarily
                        "is_media": False # Will be updated later
                    }
                elif current_message:
                    # This is a continuation line for the current message
                    current_message["content_lines"].append(line)
                # else: Handle lines before the first message match if necessary
                #    logging.warning(f"Ignoring line before first message match: {line}")

            # Add the last captured message after the loop ends
            if current_message:
                current_message["content"] = "\n".join(current_message["content_lines"])
                current_message["is_media"] = "<Media omitted>" in current_message["content"]
                del current_message["content_lines"]
                messages.append(current_message)

    except FileNotFoundError:
        logging.error(f"Error: File not found at {file_path}")
        raise # Re-raise the exception after logging
    except Exception as e:
        logging.error(f"An unexpected error occurred during parsing: {e}")
        return None # Or re-raise e depending on desired behavior

    if not messages:
        logging.warning(f"No messages parsed from file: {file_path}. Check file format.")
        return pd.DataFrame(columns=["datetime", "sender", "is_media", "content"]) # Return empty DataFrame

    logging.info(f"Successfully parsed {len(messages)} messages.")
    # Build the DataFrame
    df = pd.DataFrame(messages)

    # Ensure correct column order and types (optional but good practice)
    df = df[["datetime", "sender", "is_media", "content"]].astype({
        "datetime": "datetime64[ns]",
        "sender": "string",
        "is_media": "bool",
        "content": "string"
    })

    return df


# Mapping from user input to pandas frequency strings
TIME_GROUP_FREQ_MAP = {
    "DAY": "D",
    "WEEK": "W-MON", # Start week on Monday
    "MONTH": "MS", # Month Start frequency
}
VALID_TIME_GROUPS = list(TIME_GROUP_FREQ_MAP.keys()) + ["AUTO"]

def _determine_auto_freq(df: pd.DataFrame, max_files: int) -> Tuple[str, str]:
    """
    Determines the best grouping frequency ('D', 'W-MON', 'MS') automatically
    based on the number of resulting groups, aiming to stay under max_files.
    Starts from the most granular (Day) and moves up if the file limit is exceeded.

    Args:
        df: The DataFrame containing messages with a datetime index.
        max_files: The maximum number of output files allowed.

    Returns:
        A tuple containing the chosen frequency string ('D', 'W-MON', 'MS')
        and the corresponding user-friendly name ('DAY', 'WEEK', 'MONTH').
    """
    potential_groups = {}
    # Ensure datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index('datetime')

    for name, freq in TIME_GROUP_FREQ_MAP.items():
        grouped = df.groupby(pd.Grouper(freq=freq))
        # Count non-empty groups efficiently
        potential_groups[name] = sum(1 for _, group in grouped if not group.empty)
        logging.debug(f"Potential groups for {name} ({freq}): {potential_groups[name]}")

    if potential_groups["DAY"] <= max_files:
        logging.info(f"Auto grouping: DAY ({potential_groups['DAY']} files) selected (<= {max_files}).")
        return TIME_GROUP_FREQ_MAP["DAY"], "DAY"
    elif potential_groups["WEEK"] <= max_files:
        logging.info(f"Auto grouping: WEEK ({potential_groups['WEEK']} files) selected (<= {max_files}).")
        return TIME_GROUP_FREQ_MAP["WEEK"], "WEEK"
    else:
        logging.info(f"Auto grouping: MONTH ({potential_groups['MONTH']} files) selected (fallback).")
        return TIME_GROUP_FREQ_MAP["MONTH"], "MONTH"


def create_notebook_lm_files(
    file_path: str,
    conversation_name: str,
    save_folder_path: str,
    time_group: Literal["DAY", "WEEK", "MONTH", "AUTO"] = "AUTO",
):
    """
    Parses a WhatsApp export file, groups messages by time period,
    and saves each group into a human-readable markdown file.

    If time_group is 'AUTO' (default), it automatically selects 'DAY', 'WEEK',
    or 'MONTH' based on which frequency produces the fewest files without
    exceeding MAX_FILES (defined globally).

    Args:
        file_path: Path to the WhatsApp export file.
        conversation_name: Name of the conversation for the markdown title.
        save_folder_path: Path to the folder where markdown files will be saved.
        time_group: Time period to group messages by ('DAY', 'WEEK', 'MONTH', 'AUTO').
                    Defaults to 'AUTO'.

    Raises:
        ValueError: If time_group is invalid or parsing fails.
        FileNotFoundError: If the input file_path does not exist.
        IOError: If files cannot be written to save_folder_path.
    """
    logging.info(f"Starting NotebookLM file creation for '{conversation_name}'.")
    try:
        df = parse_whatsapp(file_path)
        if df is None:
             # Error handled and logged in parse_whatsapp
             raise ValueError(f"Failed to parse WhatsApp file: {file_path}")
        if df.empty:
            logging.warning("Parsed DataFrame is empty. No markdown files will be created.")
            return

        # Replace media messages content and drop the is_media column
        df.loc[df["is_media"], "content"] = "[[MEDIA FILE]]"
        df = df.drop(columns=["is_media"])

        # Ensure datetime column is the index for Grouper
        if not isinstance(df.index, pd.DatetimeIndex):
             df = df.set_index('datetime')

        # Determine grouping frequency
        if time_group == "AUTO":
            freq, selected_time_group_name = _determine_auto_freq(df.copy(), MAX_FILES) # Pass copy to avoid index modification issues
        elif time_group in TIME_GROUP_FREQ_MAP:
            selected_time_group_name = time_group
            freq = TIME_GROUP_FREQ_MAP[time_group]
            logging.info(f"Using specified time group: {selected_time_group_name} ({freq}).")
        else:
            raise ValueError(f"Invalid time_group: {time_group}. Choose from {VALID_TIME_GROUPS}.")

        # Create save directory if it doesn't exist
        try:
            os.makedirs(save_folder_path, exist_ok=True)
            logging.info(f"Ensured output directory exists: {save_folder_path}")
        except OSError as e:
            logging.error(f"Could not create directory {save_folder_path}: {e}")
            raise IOError(f"Could not create directory {save_folder_path}") from e


        # Group by the specified frequency
        grouped = df.groupby(pd.Grouper(freq=freq)) # Group by index

        num_groups = sum(1 for _, group in grouped if not group.empty) # Recalculate or use value from _determine_auto_freq if possible
        if num_groups == 0:
             logging.warning(f"No message groups found after grouping by {selected_time_group_name}. Check data range and grouping frequency.")
             return
        elif num_groups > MAX_FILES and time_group != "AUTO": # Add warning if manual choice exceeds limit
             logging.warning(f"Selected time group '{selected_time_group_name}' results in {num_groups} files, which exceeds the suggested limit of {MAX_FILES}.")


        date_format_file = "%Y-%m-%d"
        date_format_header = "%Y-%m-%d %H:%M"
        num_files_created = 0

        logging.info(f"Grouping messages by {selected_time_group_name} ({freq}). Expecting approx {num_groups} files.")
        for period_start, group in grouped:
            if group.empty:
                continue

            # Use the period_start provided by Grouper for consistent naming
            # Calculate end date based on actual data in the group
            start_date = period_start # This is the start of the period (e.g., start of week/month)
            end_date = group.index.max() # Actual last message time in the group

            # Format dates for filename and header
            start_date_str_file = start_date.strftime(date_format_file)
            # For single-day grouping, end date in filename is same as start date
            end_date_str_file = start_date_str_file if freq == 'D' else end_date.strftime(date_format_file)

            # Use actual min/max times for the header for accuracy
            first_msg_time = group.index.min()
            last_msg_time = end_date # already calculated
            start_date_str_header = first_msg_time.strftime(date_format_header)
            end_date_str_header = last_msg_time.strftime(date_format_header)


            # Construct filename
            filename = f"{start_date_str_file}.md" if freq == 'D' else f"{start_date_str_file}_to_{end_date_str_file}.md"
            output_path = os.path.join(save_folder_path, filename)

            # Write to markdown file
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    # Write header
                    f.write(
                        f"# Conversation: {conversation_name}\n"
                        f"## Period: {start_date_str_header} to {end_date_str_header}\n\n"
                    )
                    f.write("---\n\n") # Add a separator

                    # Write messages
                    for timestamp, row in group.iterrows():
                        # Timestamp is already the index (datetime object)
                        ts_str = timestamp.strftime(date_format_header)
                        sender = row["sender"]
                        # Indent multiline messages - replace internal newlines
                        content = row["content"].replace("\n", "\n  ")
                        f.write(f"**[{ts_str}] {sender}:**\n```\n{content}\n```\n\n") # Use code blocks for content
                num_files_created += 1
            except IOError as e:
                 logging.error(f"Could not write to file {output_path}: {e}")
                 # Decide whether to continue or stop
                 # raise IOError(f"Could not write to file {output_path}") from e # Option: Stop processing
                 continue # Option: Log error and continue with next group

        logging.info(f"Markdown file creation complete. {num_files_created} files saved to: {save_folder_path}")

    except FileNotFoundError:
         # Already logged in parse_whatsapp, just log context here
         logging.error(f"Input file not found for '{conversation_name}'.")
         raise # Re-raise to signal failure
    except ValueError as e:
         # Invalid time_group or parse error
         logging.error(f"Configuration or parsing error for '{conversation_name}': {e}")
         raise # Re-raise
    except Exception as e:
         logging.exception(f"An unexpected error occurred during NotebookLM file creation for '{conversation_name}': {e}")
         raise # Re-raise unexpected errors

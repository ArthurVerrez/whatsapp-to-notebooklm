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
# Number of lines to check for detecting date format
DATE_DETECT_LINES_LIMIT = 50

# Regex to capture the date, time, sender, and first line of content
# Handles DD/MM/YY, D/M/YY, MM/DD/YY, M/D/YY, etc. and HH:MM time format
WHATSAPP_PATTERN = re.compile(
    # Non-capturing group for the start of the line anchor ^
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2})\s*-\s*"
    r"(?P<sender>[^:]+):\s*"
    r"(?P<content>.*)"
)

# Common WhatsApp datetime formats to try (Year first is less common in exports but possible)
# Order matters: Put more specific formats (like 4-digit year) first if applicable,
# but prioritize common export formats like day/month or month/day.
# %y handles 2-digit years (00-68 -> 20xx, 69-99 -> 19xx)
POSSIBLE_DATETIME_FORMATS = [
    "%d/%m/%y %H:%M", # Day/Month/YY HH:MM (Common EU/etc.)
    "%m/%d/%y %H:%M", # Month/Day/YY HH:MM (Common US)
    "%d/%m/%Y %H:%M", # Day/Month/YYYY HH:MM
    "%m/%d/%Y %H:%M", # Month/Day/YYYY HH:MM
    # Add other potential formats if needed, e.g., with different separators
    # "%Y/%m/%d %H:%M", # Year/Month/Day HH:MM
]

def _parse_datetime_string(date_str: str, time_str: str, datetime_format: str) -> datetime:
    """
    Parses date and time strings into a datetime object using a specified format.

    Args:
        date_str: The date string (e.g., "25/12/23", "12/25/23").
        time_str: The time string (e.g., "14:30").
        datetime_format: The strptime format string (e.g., "%d/%m/%y %H:%M").

    Returns:
        A datetime object.

    Raises:
        ValueError: If the date/time strings do not match the provided format.
    """
    datetime_str = f"{date_str} {time_str}"
    return datetime.strptime(datetime_str, datetime_format)

def _detect_datetime_format(file_path: str) -> str | None:
    """
    Attempts to detect the datetime format by checking the first few message lines.
    Handles ambiguity between DD/MM and MM/DD by looking for an unambiguous date (day > 12).

    Args:
        file_path: Path to the WhatsApp export file.

    Returns:
        The detected strptime format string if successful, otherwise None.
    """
    logging.info("Attempting to detect datetime format...")
    candidate_formats = []
    checked_lines = 0

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                checked_lines += 1
                if checked_lines > DATE_DETECT_LINES_LIMIT:
                    logging.warning(f"Reached check limit ({DATE_DETECT_LINES_LIMIT} lines) for date format detection.")
                    break

                line = line.strip()
                if not line:
                    continue

                match = WHATSAPP_PATTERN.match(line)
                if not match:
                    continue # Skip lines not matching the basic message pattern

                date_str = match.group("date")
                time_str = match.group("time")
                datetime_str_sample = f"{date_str} {time_str}"

                # --- Logic --- #
                # 1. If this is the first message line found, identify initial candidates.
                if not candidate_formats:
                    possible_formats_for_this_line = []
                    for fmt in POSSIBLE_DATETIME_FORMATS:
                        try:
                            datetime.strptime(datetime_str_sample, fmt)
                            possible_formats_for_this_line.append(fmt)
                        except ValueError:
                            continue

                    if not possible_formats_for_this_line:
                        logging.warning(f"Could not parse date/time from first detected message line: '{line[:50]}...'. Continuing search.")
                        continue # Try next line
                    elif len(possible_formats_for_this_line) == 1:
                        fmt = possible_formats_for_this_line[0]
                        logging.info(f"Detected unambiguous format '{fmt}' from first message: '{line[:50]}...'")
                        return fmt # Found unique format early
                    else:
                        # Ambiguous date, store candidates and keep searching for an unambiguous one
                        candidate_formats = possible_formats_for_this_line
                        logging.info(f"Ambiguous date found ('{line[:50]}...'). Candidate formats: {candidate_formats}. Searching for unambiguous line...")
                        continue

                # 2. If we already have candidates (from a previous ambiguous line), check this line against them.
                else:
                    valid_formats_for_this_line = []
                    for fmt in candidate_formats:
                        try:
                            datetime.strptime(datetime_str_sample, fmt)
                            valid_formats_for_this_line.append(fmt)
                        except ValueError:
                            continue

                    if len(valid_formats_for_this_line) == 1:
                        # This line resolved the ambiguity
                        fmt = valid_formats_for_this_line[0]
                        logging.info(f"Resolved ambiguity. Detected format: '{fmt}' using line: '{line[:50]}...'")
                        return fmt
                    elif len(valid_formats_for_this_line) > 1:
                        # Still ambiguous, update candidates if any were eliminated (unlikely but possible)
                        candidate_formats = valid_formats_for_this_line
                        continue # Continue searching
                    else:
                        # This line didn't match any previous candidates - might indicate inconsistent format or bad line
                        logging.warning(f"Line '{line[:50]}...' did not match any candidate formats: {candidate_formats}. Skipping line.")
                        continue

    except FileNotFoundError:
        # Error will be handled by the main parse function
        return None
    except Exception as e:
        logging.error(f"Error during date format detection: {e}")
        return None

    # --- Fallback Logic (if loop finishes without definitive answer) ---
    if candidate_formats:
        # If we only checked ambiguous dates, default to the first candidate (often DD/MM)
        chosen_format = candidate_formats[0]
        logging.warning(f"Could not find unambiguous date within {DATE_DETECT_LINES_LIMIT} lines. Defaulting to first candidate format: '{chosen_format}'. This might be incorrect.")
        return chosen_format
    else:
        # If no message lines were found or parsed at all
        logging.error(f"Failed to find any valid message lines to detect date format within {DATE_DETECT_LINES_LIMIT} lines.")
        return None

def parse_whatsapp(file_path: str) -> pd.DataFrame | None:
    """
    Parse a WhatsApp export file (.txt) into a Pandas DataFrame.
    Automatically detects the date/time format.

    Handles multiline messages and identifies media omissions.

    Args:
        file_path: Path to the WhatsApp export file.

    Returns:
        Pandas DataFrame with columns: 'datetime', 'sender', 'is_media', 'content'.
        Returns None if the file cannot be read or parsed, or if format detection fails.

    Raises:
        FileNotFoundError: If the file_path does not exist.
        ValueError: If the date/time format cannot be detected or a message fails to parse with the detected format.
    """
    messages: List[Dict[str, str | datetime | bool]] = []
    current_message: Dict[str, str | datetime | bool] | None = None

    # --- 1. Detect Datetime Format ---
    detected_format = _detect_datetime_format(file_path)
    if not detected_format:
        # Error already logged by _detect_datetime_format
        # Optionally raise an error here if strict format detection is required
        # raise ValueError(f"Could not automatically detect the date/time format in {file_path}")
        return None # Or return None to indicate failure

    # --- 2. Parse Messages with Detected Format ---
    logging.info(f"Parsing WhatsApp export file: {file_path} using format '{detected_format}'")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
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
                        # Use the detected format
                        dt = _parse_datetime_string(msg_data["date"], msg_data["time"], detected_format)
                    except ValueError as e:
                         # Log the error with line number for easier debugging
                         logging.error(f"L{line_num}: Could not parse date/time in line: '{line}'. Error: {e}")
                         # Option 1: Skip this message
                         # current_message = None
                         # continue
                         # Option 2: Raise the error to stop processing
                         raise ValueError(f"L{line_num}: Could not parse date/time in line: '{line}' using format '{detected_format}'") from e
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
                #    logging.warning(f"L{line_num}: Ignoring line before first message match: {line}")

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
        # Catch potential errors during the main parsing loop after format detection
        logging.error(f"An unexpected error occurred during message parsing: {e}")
        return None # Or re-raise e depending on desired behavior

    if not messages:
        logging.warning(f"No messages parsed from file: {file_path}. Check file format and content.")
        # Return empty DataFrame with correct columns even if no messages parsed
        return pd.DataFrame(columns=["datetime", "sender", "is_media", "content"])

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
        # Make a copy before setting index if the original df is needed elsewhere
        df_indexed = df.set_index('datetime')
    else:
        df_indexed = df

    for name, freq in TIME_GROUP_FREQ_MAP.items():
        grouped = df_indexed.groupby(pd.Grouper(freq=freq))
        # Count non-empty groups efficiently
        potential_groups[name] = sum(1 for _, group in grouped if not group.empty)
        logging.debug(f"Potential groups for {name} ({freq}): {potential_groups[name]}")

    # Determine frequency based on counts and max_files limit
    if potential_groups["DAY"] <= max_files:
        logging.info(f"Auto grouping: DAY ({potential_groups['DAY']} files) selected (<= {max_files}).")
        return TIME_GROUP_FREQ_MAP["DAY"], "DAY"
    elif potential_groups["WEEK"] <= max_files:
        logging.info(f"Auto grouping: WEEK ({potential_groups['WEEK']} files) selected (<= {max_files}).")
        return TIME_GROUP_FREQ_MAP["WEEK"], "WEEK"
    else:
        # If even monthly grouping exceeds max_files, log a warning but proceed
        if potential_groups["MONTH"] > max_files:
             logging.warning(f"Auto grouping: MONTH selected, but estimated file count ({potential_groups['MONTH']}) exceeds limit ({max_files}).")
        else:
             logging.info(f"Auto grouping: MONTH ({potential_groups['MONTH']} files) selected (fallback or within limit).")
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
    or 'MONTH' based on which frequency produces a number of files under MAX_FILES.

    Args:
        file_path: Path to the WhatsApp export file.
        conversation_name: Name of the conversation for the markdown title.
        save_folder_path: Path to the folder where markdown files will be saved.
        time_group: Time period to group messages by ('DAY', 'WEEK', 'MONTH', 'AUTO').
                    Defaults to 'AUTO'.

    Raises:
        ValueError: If time_group is invalid, parsing fails, or date format cannot be determined.
        FileNotFoundError: If the input file_path does not exist.
        IOError: If files cannot be written to save_folder_path.
    """
    logging.info(f"Starting NotebookLM file creation for '{conversation_name}'.")
    try:
        # Parse whatsapp data (includes date format detection)
        df = parse_whatsapp(file_path)
        if df is None:
             # Error handled and logged in parse_whatsapp
             raise ValueError(f"Failed to parse WhatsApp file (or detect date format): {file_path}")
        if df.empty:
            logging.warning("Parsed DataFrame is empty. No markdown files will be created.")
            return

        # Replace media messages content and drop the is_media column
        df.loc[df["is_media"], "content"] = "[[MEDIA FILE]]"
        df = df.drop(columns=["is_media"])

        # Ensure datetime column is the index for Grouper and frequency determination
        if not isinstance(df.index, pd.DatetimeIndex):
             df_indexed = df.set_index('datetime')
        else:
             df_indexed = df # Already has datetime index

        # Determine grouping frequency
        if time_group == "AUTO":
            # Pass the DataFrame with datetime index to the determination function
            freq, selected_time_group_name = _determine_auto_freq(df_indexed, MAX_FILES)
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


        # Group by the specified frequency using the indexed DataFrame
        grouped = df_indexed.groupby(pd.Grouper(freq=freq)) # Group by index

        # Estimate number of groups to be created (non-empty ones)
        # We recalculate here based on the final chosen freq
        num_groups = sum(1 for _, group in grouped if not group.empty)

        if num_groups == 0:
             logging.warning(f"No message groups found after grouping by {selected_time_group_name}. Check data range and grouping frequency.")
             return
        # Warn if manually selected group exceeds limit (AUTO handles this internally)
        elif num_groups > MAX_FILES and time_group != "AUTO":
             logging.warning(f"Selected time group '{selected_time_group_name}' results in {num_groups} files, which exceeds the suggested limit of {MAX_FILES}.")
        elif num_groups > MAX_FILES and time_group == "AUTO":
             # This case should ideally be handled by _determine_auto_freq choosing MONTH
             # But add a warning just in case something unexpected happens or MONTH also exceeds.
             logging.warning(f"AUTO grouping resulted in {num_groups} files (using {selected_time_group_name}), which exceeds the target limit of {MAX_FILES}. Proceeding anyway.")

        date_format_file = "%Y-%m-%d"
        date_format_header = "%Y-%m-%d %H:%M"
        num_files_created = 0

        logging.info(f"Grouping messages by {selected_time_group_name} ({freq}). Expecting {num_groups} files.")
        # Iterate through the groups generated by groupby
        for period_start, group in grouped:
            if group.empty:
                continue

            # Use the period_start provided by Grouper for consistent naming
            # Calculate end date based on actual data in the group
            start_date = period_start # This is the start of the period (e.g., start of week/month)
            end_date = group.index.max() # Actual last message time in the group

            # Format dates for filename and header
            start_date_str_file = start_date.strftime(date_format_file)
            # For single-day grouping, filename is just the date
            end_date_str_file = start_date_str_file if freq == 'D' else end_date.strftime(date_format_file)

            # Use actual min/max times for the header for accuracy
            first_msg_time = group.index.min()
            last_msg_time = end_date # already calculated
            start_date_str_header = first_msg_time.strftime(date_format_header)
            end_date_str_header = last_msg_time.strftime(date_format_header)


            # Construct filename
            # Use only start date for daily files, range otherwise
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
                    # group.iterrows() iterates over the DataFrame rows in the group
                    for timestamp, row in group.iterrows():
                        # Timestamp is already the index (datetime object)
                        ts_str = timestamp.strftime(date_format_header) # Use the consistent header format
                        sender = row["sender"]
                        # Indent multiline messages - replace internal newlines
                        content = str(row["content"]).replace("\n", "\n  ") # Ensure content is string
                        f.write(f"**[{ts_str}] {sender}:**\n```\n{content}\n```\n\n") # Use code blocks for content
                num_files_created += 1
            except IOError as e:
                 logging.error(f"Could not write to file {output_path}: {e}")
                 # Decide whether to continue or stop
                 # raise IOError(f"Could not write to file {output_path}") from e # Option: Stop processing
                 continue # Option: Log error and continue with next group

        logging.info(f"Markdown file creation complete. {num_files_created} files saved to: {save_folder_path}")

    except FileNotFoundError:
         # Already logged by parse_whatsapp or _detect_datetime_format
         logging.error(f"Input file not found for '{conversation_name}'.")
         # No need to re-raise usually, as the process stops gracefully
    except ValueError as e:
         # Invalid time_group or parse error
         logging.error(f"Configuration or processing error for '{conversation_name}': {e}")
         # No need to re-raise usually
    except Exception as e:
         logging.exception(f"An unexpected error occurred during NotebookLM file creation for '{conversation_name}': {e}")
         # Consider re-raising for unexpected errors if needed
         # raise

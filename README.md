# WhatsApp to NotebookLM Converter

**Quick Steps:**

1.  Export chat from WhatsApp (`.txt` file).
2.  Clone this repository.
3.  Set up a Python virtual environment.
4.  Install dependencies (`pip install -r requirements.txt`).
5.  Run `python main.py path/to/_chat.txt "Conversation Name"`.
6.  Upload the generated Markdown files from the `output` folder to NotebookLM.

This script parses a WhatsApp chat export file (.txt) and converts it into multiple Markdown files, grouped by day, week, or month. These files are formatted for easy import into [Google NotebookLM](https://notebooklm.google.com/) as sources, allowing you to query and analyze your conversation history.

## Features

- Parses standard WhatsApp text exports (detects `DD/MM/YY` vs `MM/DD/YY` automatically).
- Handles multi-line messages.
- Replaces `<Media omitted>` messages with `[[MEDIA FILE]]` placeholder.
- Groups messages into separate Markdown files by Day, Week (starting Monday), or Month.
- **Automatic Grouping (`AUTO`):** Automatically selects the best time grouping (Day, Week, or Month) to keep the number of output files below a specified limit (default: 400), ensuring compatibility with NotebookLM's source limit.
- Command-line interface for easy execution.

## Setup

**1. Export Your WhatsApp Chat:**

- Open the WhatsApp chat you want to export.
- Tap the contact or group name at the top.
- Scroll down and select **Export Chat**.
- Choose **Without Media** (the script currently ignores media files).
- Select how you want to save or send the exported `.zip` file (e.g., save to Files, email to yourself).
- **Unzip the exported file.** Inside the unzipped folder, you will find a `_chat.txt` (or similar named `.txt`) file. This is the file you will use with the script.

**2. Clone the Repository:**

```bash
git clone https://github.com/ArthurVerrez/whatsapp-to-notebooklm
cd whatsapp-to-notebooklm
```

**3. Create and Activate Virtual Environment:**

- **macOS/Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```
- **Windows:**
  ```bash
  python -m venv venv
  .\venv\Scripts\activate
  ```

**4. Install Dependencies:**

```bash
pip install -r requirements.txt
```

## Usage

Run the script from your terminal using the `main.py` file. You need to provide the path to your WhatsApp export file (`_chat.txt`) and a name for the conversation.

**Basic Command Structure:**

```bash
python main.py <path_to_whatsapp_export.txt> "<Conversation Name>" [options]
```

**Arguments:**

- `<path_to_whatsapp_export.txt>`: (Required) The path to the `_chat.txt` file you extracted from the WhatsApp export.
- `"<Conversation Name>"`: (Required) A descriptive name for the chat (e.g., "Project Group Chat", "Family Chat"). Enclose in quotes if it contains spaces.

**Options:**

- `-o`, `--output-folder <folder_path>`: Specifies the directory where the generated Markdown files will be saved. Defaults to `output/` in the current directory.
- `-t`, `--time-group <GROUP>`: Specifies how to group messages. Choices are `DAY`, `WEEK`, `MONTH`, `AUTO`. Defaults to `AUTO`.
  - `AUTO`: Automatically selects DAY, WEEK, or MONTH to stay under the 400 file limit.

**Example:**

To process a file named `_chat.txt` located in the current directory and call the conversation "Conversation with a friend", saving the output to the default `output` folder and using automatic time grouping:

```bash
python main.py _chat.txt "Conversation with a friend"
```

This will create Markdown files (e.g., `2023-10-26.md`, `2023-10-27_to_2023-11-02.md`, etc.) inside the `output` folder.

## Importing into NotebookLM

1.  Go to [https://notebooklm.google.com/](https://notebooklm.google.com/).
2.  Create a **New notebook**.
3.  In the "Sources" panel on the left, click the **+** icon or "Add sources".
4.  Choose **Upload files**.
5.  Navigate to the output folder (e.g., `output/`) created by the script.
6.  Select **all** the generated `.md` files (up to the 400 file limit).
7.  Click **Open** or **Upload**.
8.  Wait for NotebookLM to process all the uploaded files. You'll see them appear in the Sources panel.
9.  Once processing is complete, you can start asking questions about your conversation.
10. **Optional: Generate Audio Overview:** Click the **Audio Overview** button (often looks like a play button or waveform) at the top of the Sources panel and select **Generate**. NotebookLM will create an audio summary based on the content of your uploaded files.

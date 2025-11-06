import pathlib
import json
from collections import defaultdict

INPUT_DIR = pathlib.Path("data/json")
OUTPUT_DIR = pathlib.Path("data/threads")

def join_threads():

    # group messages by their thread ID
    threads = defaultdict(list)

    # Read and convert all JSON files
    json_files = sorted(list(INPUT_DIR.rglob("*.json")))
    print(f"Found {len(json_files)} message files to process.")


    # For loop to transform and group json files
    for file_path in json_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # There is a better way of doing this but, we will cross that bridge later
        # Remake the URL link
        year_month = file_path.parent.name
        html_filename = file_path.stem + ".html"
        url = f"http://archive.ambermd.org/{year_month}/{html_filename}"

        # Dictionary
        message = {
            "message_id": data.get("message_id"),
            "author": data.get("author_name"),
            "date_raw": data.get("date_raw"),
            "body": data.get("body_text"),
            "url": url
        }

        # Grouping message
        thread_id_key = data.get("thread_id")


        # If they are the same append th emessage
        if thread_id_key and message["message_id"]:
            threads[thread_id_key].append(message)

    # Make output if it doesnt exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Process each thread and write it to a new, combined file
    for thread_subject, messages in threads.items():

        # Sort by timestamp
        messages.sort(key=lambda m: m['message_id'])

        # Message id
        original_message = messages[0]
        op_message_id = original_message['message_id']

        # Add "in_reply_to": 1709295074 requirement
        for i in range(1, len(messages)):
            messages[i]['in_reply_to'] = op_message_id

        # final threat object
        final_thread = {
            "thread_id": op_message_id,
            "subject": f"[AMBER] {thread_subject}",
            "messages": messages
        }

        # write this into a json file
        output_filename = f"{op_message_id}.json"
        output_path = OUTPUT_DIR / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            # write python data to json
            json.dump(final_thread, f, indent=2, ensure_ascii=False)

def main():
    join_threads()
    print(f"Check the output files in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
"""
    1st. Read both JSON file threads
    (ex. amber_202001 & amber_202002)
    2nd. Start with 2nd file and Check if subject starts with "Re:"
    3rd. Check previous thread file to find a matching subject
    4th. Modify the previous JSON file and add the corresponding subject thread
"""
import os
import json
from pathlib import Path

previousMonthFile = "amber_202001"
currentMonthFile = "amber_202002"


def readData(folderName) -> list:
    folder_path = folderName
    all_data = []

    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            with open(os.path.join(folder_path, filename), "r", encoding="utf-8") as f:
                all_data.append(json.load(f))
    return all_data


def compareData(previousMonth, currentMonth):
    for curr in currentMonth:
        replySubject = curr["subject"]

        if replySubject.lower().startswith("re:"):
            # Remove "Re:" and any leading/trailing spaces
            replyCore = replySubject[3:].strip()

            for prev in previousMonth:
                rootSubject = prev["subject"].strip()

                # Only consider original subjects (no "Re:")
                if not rootSubject.lower().startswith("re:"):
                    # Compare case-insensitively
                    if replyCore.lower() == rootSubject.lower():
                        curr["messages"][0]["in_reply_to"] = prev["messages"][0]["message_id"]
                        prev["messages"].extend(curr["messages"])


def writeToJSON(folder_name, threads):

    Path(folder_name).mkdir(parents=True, exist_ok=True)

    for thread in threads:
        thread_id = thread["thread_id"]
        file_path = Path(folder_name) / f"{thread_id}.json"

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)

    print(f"Wrote data to {folder_name}.json")


def main():
    previousMonth = readData(previousMonthFile)
    currentMonth = readData(currentMonthFile)

    compareData(previousMonth, currentMonth)
    # print(json.dumps(previousMonth, indent=2))

    writeToJSON("amber_202001", previousMonth)


main()

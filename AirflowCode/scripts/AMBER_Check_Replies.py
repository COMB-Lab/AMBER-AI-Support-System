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

previousMonthFile = Path("../CleanData/AMBER2020/amber_202002")
currentMonthFile = Path("../CleanData/AMBER2020/amber_202003")


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
        replySubject = curr.get("subject").strip()
        if replySubject.lower().startswith("re:"):
            replyCore = replySubject[3:].strip()

            for prev in previousMonth:
                rootSubject = (prev.get("subject") or "").strip()
                if not rootSubject.lower().startswith("re:") and replyCore.lower() == rootSubject.lower():
                    print("Match")
                    existing_ids = set()
                    for m in prev.get("messages", []):
                        mid = m.get("message_id")
                        if mid is not None:
                            existing_ids.add(mid)

                    new_msgs = []
                    for m in curr.get("messages", []):
                        mid = m.get("message_id")
                        if mid not in existing_ids:
                            new_msgs.append(m)

                    if new_msgs:
                        if prev.get("messages") and "in_reply_to" not in new_msgs[0]:
                            try:
                                new_msgs[0]["in_reply_to"] = prev["messages"][0]["message_id"]
                            except (IndexError, KeyError, TypeError):
                                pass

                        prev.setdefault("messages", []).extend(new_msgs)
                    break


def writeToJSON(folder_name, threads):
    Path(folder_name).mkdir(parents=True, exist_ok=True)
    for thread in threads:
        thread_id = thread.get("thread_id", "thread")
        file_path = Path(folder_name) / f"{thread_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
    print(f"Wrote data to {folder_name}.json")


def main():
    base = Path("../CleanData")
    foldersWorkingWith = []

    for parentFolder in os.listdir(base):
        entry_path = os.path.join(base, parentFolder)
        for subFolder in os.listdir(entry_path):
            if os.path.isdir(entry_path):
                entry_path2 = os.path.join(base, parentFolder, subFolder)
                foldersWorkingWith.append(entry_path2)

    for i in range(len(foldersWorkingWith)):
        prev = foldersWorkingWith[i]

        if i + 1 in range(len(foldersWorkingWith)):
            curr = foldersWorkingWith[i+1]
            previousMonth = readData(prev)
            currentMonth = readData(curr)
            compareData(previousMonth, currentMonth)
            writeToJSON(prev, previousMonth)

        print(f"Previous: {prev}\n Current : {curr} ")

    # previousMonth = readData(previousMonthFile)
    # currentMonth = readData(currentMonthFile)
    # compareData(previousMonth, currentMonth)
    # print(json.dumps(previousMonth, indent=2))
    # writeToJSON(previousMonthFile, previousMonth)


main()

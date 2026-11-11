
import csv
from collections import defaultdict

counts = defaultdict(lambda: [0, 0])

with open("eval_manual_check.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        value = row["correct_1_or_0"].strip()

        if value in ("0", "1"):
            counts[row["type"]][0] += int(value)
            counts[row["type"]][1] += 1

print("\n======= MANUAL ACCURACY REPORT =======")

for category, (correct, total) in sorted(counts.items()):
    accuracy = correct / total * 100 if total else 0
    print(f"{category:25s}: {accuracy:.2f}% ({correct}/{total})")

print("======================================")

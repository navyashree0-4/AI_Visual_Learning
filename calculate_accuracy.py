
import csv
import os
from collections import defaultdict

FILE = "eval_results.csv"

if not os.path.exists(FILE):
    print("ERROR: eval_results.csv not found!")
    raise SystemExit

metrics = defaultdict(list)

with open(FILE, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)

    for row in reader:
        for key, value in row.items():
            if key.endswith("%") and value:
                try:
                    metrics[key].append(float(value))
                except ValueError:
                    pass

print("\n========== EDUVISION ACCURACY REPORT ==========\n")

for metric, values in sorted(metrics.items()):
    average = sum(values) / len(values)
    print(f"{metric:30s}: {average:.2f}%")
    print(f"  Successful measurements: {len(values)}")

print("\n===============================================")
print("NOTE: These are automated evaluation scores.")
print("They are not independently verified factual accuracy.")

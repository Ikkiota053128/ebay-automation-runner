"""保存の直前に、最新の台帳（データ置き場の main）へ、この回の変更（台帳の変更の記録）だけを当て直す。
同時に動いた別のプログラムの変更を消さないため（設計書 5章「保存する直前に最新の台帳を読み直し、SKUごと・自分の列だけ合わせる」）。
使い方：python3 ledger_merge.py <データ置き場> <変更の記録.json>（記録が無ければ何もしない）"""
import csv, json, os, subprocess, sys

repo, journal = sys.argv[1], sys.argv[2]
if not os.path.exists(journal):
    sys.exit(0)
ch = json.load(open(journal, encoding="utf-8"))
remote = subprocess.run(["git", "-C", repo, "show", "origin/main:台帳.csv"], capture_output=True, text=True).stdout
rows = list(csv.DictReader(remote.splitlines())) if remote else []
cols = list(rows[0].keys()) if rows else []
by = {r["SKU"]: r for r in rows}
for c in ch:
    for r in c["rows"]:
        if r["SKU"] in by:
            for k in c["cols"]:
                by[r["SKU"]][k] = r.get(k, "")
        else:
            n = {k: r.get(k, "") for k in (cols or r.keys())}
            rows.append(n)
            by[r["SKU"]] = n
before = len(list(csv.DictReader(remote.splitlines()))) if remote else 0
if len(rows) < before:
    sys.exit("台帳の行が減るので保存しない")
with open(os.path.join(repo, "台帳.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in cols})
print("台帳：最新に %d回分の変更を当て直した" % len(ch))

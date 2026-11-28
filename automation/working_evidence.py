"""動作確認済みとした品の「根拠」を抜き出す（読むだけ）。11/28 11:11 オーナー「根拠を確かめて」
- 対象：タイトルに Tested Working がある出品中の品＋ data/判定/動作確認済みの読み直し_*.json の品。
- 仕入れ先の説明を読み直し（src_working_check と同じ読み方）、動作の言葉の前後の文と、近くの気になる言葉（不具合・難あり・一部・現状 など）を抜き出す。
- 結果は data/判定/動作確認の根拠.json。人（AI）が読んで、但し書き・決まり文句の品を見つける。eBay は変えない。"""
import glob, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, read_ledger, save_json, load_json
import cond_note
from stock_watch import rakuten_item

WORK = re.compile(r"動作確認済|動作品|正常に動作|動作OK|動作ok|動作良好|作動確認済|作動品")
WARN = re.compile(r"不具合|難あり|難有|一部|現状|ジャンク|動作未確認|未確認|保証な|保証は|ノークレーム|ノーリターン|故障|不良|反応が|反応し|誤作動|使用不可|部品取り|動作不|できません|しない|しません")
PG = None


def browser_text(url):
    global PG
    if PG is None:
        from playwright.sync_api import sync_playwright
        PG = sync_playwright().start().chromium.launch().new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    time.sleep(random.uniform(15, 25))
    PG.goto(url.split("?")[0], wait_until="domcontentloaded", timeout=45000)
    PG.wait_for_timeout(8000)
    return PG.inner_text("body")[:30000]


led = {r["SKU"]: r for r in read_ledger()}
skus = [s for s, r in led.items() if r.get("状態") == "出品中" and re.search(r"Tested Working", r.get("タイトル") or "")]
for f in glob.glob(os.path.join(ROOT, "data", "判定", "動作確認済みの読み直し_*.json")):
    skus += [x["SKU"] for x in load_json(f, {}).get("動作確認済み", [])]
skus = list(dict.fromkeys(skus))
out = {"時刻": jst(), "品": []}
t_end = time.time() + 70 * 60
for sku in skus:
    if time.time() > t_end:
        break
    r = led.get(sku) or {}
    u = r.get("仕入元URL") or ""
    txt = ""
    try:
        if "rakuten" in u:
            it = rakuten_item(u, r.get("タイトル", ""))
            txt = ("%s\n%s" % (it.get("itemName", ""), it.get("itemCaption", ""))) if it else ""
            time.sleep(1.1)
        elif re.search(r"mercari|fril\.jp", u):
            txt = browser_text(u)
        elif u:
            txt = cond_note.source_text({"url": u})
            time.sleep(3)
    except Exception as e:
        txt = ""
    txt = re.sub(r"[ \t　]+", " ", txt)
    hits = []
    for m in WORK.finditer(txt):
        a, b = max(0, m.start() - 90), min(len(txt), m.end() + 110)
        sn = txt[a:b].replace("\n", " / ")
        if sn not in hits:
            hits.append(sn)
    warn = sorted(set(WARN.findall(txt)))
    out["品"].append({"SKU": sku, "状態": r.get("状態"), "タイトル": (r.get("タイトル") or "")[:80], "仕入元URL": u,
                     "読めた": bool(txt), "動作の言葉の前後": hits[:4], "気になる言葉": warn, "説明の長さ": len(txt)})
save_json(os.path.join(ROOT, "data", "判定", "動作確認の根拠.json"), out)
print("見た", len(out["品"]), "読めた", sum(1 for x in out["品"] if x["読めた"]))

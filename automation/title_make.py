"""タイトルを教科書の形で作る（11/23 19:25 オーナー「原則は3つだけ覚えてください」・19:26「OK」）。
形：ブランド名 ＋ 型番 ＋ 商品の種類 ＋ 状態・特徴 ＋ 付属品 ＋ From Japan（80文字まで）。
- 状態は仕入れ先が書いた言葉だけから（cond_note の結果）。書いていなければ Used（盛らない）。
- 付属品は仕入れ先の説明で分かったときだけ（w/ Box・w/ Charger など）。
- 型番は仕入れ先の商品名・説明と照合する（check_model）。合わなければ出さない。"""
import re


def norm(s):
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper().replace("－", "-"))


def check_model(model, *texts):
    """型番（英数字だけにしたもの）が、仕入れ先の商品名・説明のどれかに入っているか"""
    m = norm(model)
    if len(m) < 2:
        return False
    import unicodedata
    return any(m in norm(unicodedata.normalize("NFKC", t or "")) for t in texts)


def cond_word(cond, cn, src=""):
    if cond < 3000:
        return "New"
    n = " ".join(cn.get("notes") or [])
    if re.search(r"ジャンク|部品取り", src or ""):
        return "For Parts"
    m = re.search(r"rank: ([SABCD])", n)
    if "Near mint" in n or (m and m.group(1) == "S"):
        return "Near Mint"
    if "Excellent" in n or (m and m.group(1) == "A"):
        return "Excellent"
    if "Good condition" in n or (m and m.group(1) == "B"):
        return "Good"
    if "Visible signs of use" in n or (m and m.group(1) in "CD"):
        return "Fair"
    return "Used"


# 型番の頭からはっきり分かるシリーズ名（買い手が検索する名前）
SERIES = [(r"^Casio$", r"^EX-", "Exilim"), (r"^Casio$", r"^(GA|GW|GST|GMW|DW|GD|GBD|GM|GBA|GR|GG|MTG|MRG|GPR|GWG|GWF|GN|GLX)-", "G-Shock"),
          (r"^Casio$", r"^(BA|BGA|BG|MSG|BGD)-", "Baby-G"), (r"^Panasonic$", r"^DMC-|^DC-", "Lumix"),
          (r"^Sony$", r"^DSC-", "Cyber-shot"), (r"^Sony$", r"^WM-", "Walkman"), (r"^Sony$", r"^MZ-", "MiniDisc Walkman"),
          (r"^Sony$", r"^(HDR|FDR|DCR)-", "Handycam"), (r"^Canon$", r"^IXY", "IXUS ELPH"), (r"^Nikon$", r"^(COOLPIX|S\d{3,4}|P\d{3,4}|W\d{3})", "Coolpix"),
          (r"^Fujifilm$|^Fuji$", r"^(XP|F|Z|J|S)\d", "FinePix"), (r"^Olympus$", r"^TG-", "Tough"),
          (r"^Pentax$", r"^(WG|Optio)", "Optio")]


def series(brand, model, kind_word):
    for b, m, w in SERIES:
        if re.search(b, brand or "", re.I) and re.search(m, model or "", re.I) and w.lower() not in (kind_word or "").lower():
            return w
    return ""


ACC = [("Body only", "Body Only"), ("Box", "w/ Box"), ("Charger", "w/ Charger"), ("Manual", "w/ Manual"),
       ("Case", "w/ Case"), ("Strap", "w/ Strap"), ("Cap", "w/ Cap")]


def build(brand, model, kind_word, cond, cn, src=""):
    head = re.sub(r"\s+", " ", "%s %s %s %s" % (brand, model, series(brand, model, kind_word), kind_word)).strip()
    parts = [cond_word(cond, cn, src)]
    box = cn.get("box") or ""
    acc = [word for key, word in ACC if key in box and key != "Body only"]
    if "Body only" in box and not acc:
        acc = ["Body Only"]   # 付属品が何も無いときだけ（「本体のみ」と「充電器付き」が両方は書かない）
    parts += acc
    t = head
    for p in parts + ["From Japan"]:
        if p.lower() in t.lower():   # 同じ言葉を2回書かない（w/ Box … w/ Box など）
            continue
        if len(t) + 1 + len(p) <= 80:
            t += " " + p
    return t[:80]


COLORS = [("ブラック|黒", "Black"), ("ホワイト|白", "White"), ("シルバー|銀", "Silver"), ("ゴールド|金色", "Gold"), ("レッド|赤", "Red"),
          ("ブルー|青", "Blue"), ("ネイビー|紺", "Blue"), ("グリーン|緑", "Green"), ("イエロー|黄", "Yellow"), ("ピンク", "Pink"),
          ("オレンジ", "Orange"), ("ブラウン|茶", "Brown"), ("グレー|灰", "Gray"), ("パープル|紫", "Purple"), ("ベージュ", "Beige")]


def colors_in(t):
    """商品名の色（日本語・英語）"""
    import unicodedata
    t = unicodedata.normalize("NFKC", t or "")
    found = {en for rx, en in COLORS if re.search(rx, t)}
    found |= {en for _, en in COLORS if re.search(r"\b%s\b" % en, t, re.I)}
    return found


# 11/28 09:27 オーナー「仕入先で動作確認済みの商品は出品タイトルに必ず動作確認済みときさいして！」
# 仕入れ先が「動作確認済み」と書いた品（cond_note の func が Reported working）は、タイトルの状態の前に「Tested Working」を必ず入れる。
# 80文字を超えるときは、型番より後ろの特徴の言葉を後ろから外して入れる（ブランド・型番・状態・From Japan は残す）。
WORK = "Tested Working"
_TAILW = re.compile(r"^(.+?) ((?:New|Used|Near Mint|Excellent|Good|Fair)(?: w/ \S+| Body Only)* From Japan)$")


def is_working(cn, src_name=""):
    return bool((cn or {}).get("func", "").startswith("Reported working")) and not re.search(r"ジャンク|部品取り|動作未確認|動作不良|故障", src_name or "")


def add_working(title):
    t = re.sub(r"\s+", " ", title or "").strip()
    if re.search(r"\btested\b|\bworking\b", t, re.I):
        return t
    m = _TAILW.match(t)
    if m:
        head, tail = m.group(1).split(" "), m.group(2)
    elif t.endswith(" From Japan"):
        head, tail = t[:-len(" From Japan")].split(" "), "From Japan"
    else:
        head, tail = t.split(" "), ""
    while len(" ".join(head + [WORK] + ([tail] if tail else []))) > 80 and len(head) > 2:
        head.pop()
    return " ".join(head + [WORK] + ([tail] if tail else []))[:80]

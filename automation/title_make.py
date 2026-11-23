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


ACC = [("Body only", "Body Only"), ("Box", "w/ Box"), ("Charger", "w/ Charger"), ("Manual", "w/ Manual"),
       ("Case", "w/ Case"), ("Strap", "w/ Strap"), ("Cap", "w/ Cap")]


def build(brand, model, kind_word, cond, cn, src=""):
    head = re.sub(r"\s+", " ", "%s %s %s" % (brand, model, kind_word)).strip()
    parts = [cond_word(cond, cn, src)]
    box = cn.get("box") or ""
    for key, word in ACC:
        if key in box:
            parts.append(word)
    t = head
    for p in parts + ["From Japan"]:
        if len(t) + 1 + len(p) <= 80:
            t += " " + p
    return t[:80]

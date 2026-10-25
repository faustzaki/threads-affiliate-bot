import json
import random
import re
import urllib.request
import urllib.error
from config import NINEROUTER_URL, NINEROUTER_KEY, DEFAULT_MODEL

ANGLES_SIANG = [
    # Makanan, Kopi & Kantuk Siang
    "Food coma siang: kenyang makan siang lgsg mata 5 watt di meja kerja/kelas, kopi ga mempan.",
    "Dilema jajan makan siang: bingung nentuin makan siang ampe jam istirahat abis, ujung-ujungnya geprek lagi.",
    "Asupan dingin: matahari terik bat rasanya pengen nyemplung ke dalem gelas es teh solo jumbo.",
    "Duit jajan siang: niat hemat bawa bekel, tapi pas diajak jajan es kopi susu sama temen lgsg goyah.",
    # Cuaca, Jalanan & Commute Siang
    "Panas aspal & ojol: siang bolong naik ojol rasanya kayak ayam panggang berjalan, bedak luntur kena helm.",
    "AC ruangan vs luar: di dalem ruangan kedinginan kyk kutub, pas keluar lgsg ditampar hawa panas neraka.",
    # Fashion & Outfit Struggle Siang
    "Salah kostum: sok ide pake outfit tebel/gelap siang ini, pas keluar lgsg nyesel berasa sauna berjalan.",
    "Kemeja lecek ojol: sebelum berangkat rapi disetrika, pas nyampe kantor kemeja udah remuk kayak kerupuk.",
    "Celana begah: celana pas berdiri cakep, pas duduk 4 jam di kantor/kampus kancingnya berasa mau meledak.",
    "Baju gerah vs adem: fast fashion mall bahan poly bikin ketiak basah kuyup vs katun/linen lokal yang breathable.",
    "Paha tebel mobile: jalan buru-buru pas siang bolong paha gesek ga karuan, butuh cuttingan celana yg longgar.",
    "Jedai / printilan ilang: iket rambut ilang mulu, rambut gerah lepek kena keringat siang.",
    # Observasi & Absurditas Siang
    "Energi orang produktif: jam 1 siang liat orang masih semangat kerja tuh energinya dapet dari katering mana sih.",
    "Jam kritis: jam 14:00 itu jam paling lama dalam peradaban manusia, jarum jam rasanya mogok jalan.",
    "Pikiran melayang: duduk di meja kantor/kelas tapi jiwa udah di kasur nonton netflix."
]

ANGLES_MALAM = [
    # Ritual Santai, Daster & Kasur
    "Ganti baju pw: balik kos/rumah mandi air anget terus pake baju paling gembel/celana bolong paling nyaman sedunia, war is over beneran.",
    "Rebahan mager: udah rebahan di kasur terus inget tumblr minum ketinggalan di meja, dilema mager tingkat dewa.",
    "Aroma comfort: selonjoran di kasur abis balur minyak telon/body lotion, scrolling santai nol beban.",
    # Makanan & Craving Malam
    "Penyakit laper tengah malem: nonton mukbang mie pedes jam 10 malem, air liur netes tp kaki mager bgt ke dapur.",
    "Jajan martabak/mie: niat diet seharian buyar gara-gara abang martabak/mie tek-tek lewat depan pager.",
    # Olshop & Belanja Malam
    "Rabbit hole keranjang oren: niat cuma scrolling 5 menit sebelum tidur, tau-tau 2 jam mantengin printilan rumah tangga.",
    "Drama checkout tengah malem: masukin barang 100 biji ke wishlist, pas checkout cuma printilan jedai 3 rebuan.",
    "Compare rating ga kelar: jam 11 malem masih riset perbedaan bahan katun combed 24s vs 30s di kolom ulasan toko.",
    # Dilema Outfit Besok
    "Lemari penuh tapi 'gapunya baju': bengong depan lemari 15 menit mikirin outfit besok, berasa bajunya ilang semua.",
    "Males nyetrika: liat tumpukan baju bersih di kursi yg belum disetrika, pura-pura ga liat terus tarik selimut.",
    # Skincare & Overthinking
    "Mager skincare: mata udah sepet bgt tapi inget muka belum double cleansing, berantem sama rasa males.",
    "Overthinking random: tiba-tiba keinget momen malu-maluin pas smp pas udah mau merem.",
    "Dialog begadang: 'gue: malem ini tidur jam 10', also gue jam 1: scroll drama Threads warga."
]

ANGLES = ANGLES_SIANG + ANGLES_MALAM

FORMAT_STYLES = [
    "One-liner ceplas-ceplos (1-2 baris pendek, kering, sarkas atau absurd)",
    "Dialog / monolog batin (contoh: 'gue pas mau checkout: ... \notak gue: ...' atau 'gue jam 1 siang:')",
    "Cerita mikro kejadian hari ini (2-3 baris alur santai, ada kejadian kecil)",
    "Tanya warga / adu nasib (lempar pertanyaan receh buat mancing reply santai)",
    "Curhat to the point tanpa basa-basi",
    "Observasi random (kebiasaan absurd manusia yang baru disadari)"
]

LENGTHS = [
    "short (1-2 baris singkat, punchy, to the point)",
    "medium (2-3 baris curhat santai dan observasi)",
    "long (3-4 baris storytelling atau review detail)"
]

HOOKS = [
    "Ceplas-ceplos spontan tanpa basa-basi",
    "Capslock syok / panik lucu (ANJIRRR, WADUHHH, PLISSS, YA ALLAHHH)",
    "Observasi santai (kalian sadar ga sih, baru sadar, kenapa ya...)",
    "Dialog singkat (gue: ... | also gue: ...)",
    "Lempar tanya langsung ke pembaca"
]

def build_system_prompt(angle: str, length_style: str, hook_style: str) -> str:
    return f"""Kamu adalah cewek Gen Z Indonesia yang aktif di Threads.
Karakter: Santai, jujur, relatable, suka curhat outfit/belanjaan, anti-zonk, skeptis sama klaim toko lebay.

Panduan Penulisan Kali Ini:
- Sudut Pandang: {angle}
- Panjang Teks: {length_style}
- Gaya Pembuka: {hook_style}

Aturan Gaya Bahasa (WAJIB):
1. Dominan huruf kecil (lowercase). Huruf kapital HANYA dipakai untuk capslock dramatis/lucu (ANJIRRR, PLISSS, WADUHHH, FINALLY).
2. Pakai singkatan chat santai Indonesia (pdhl, bgt, lgsg, co, sm, kyk, gausa, nyari, bat).
3. Hindari memaksakan istilah klise ('in this economy', 'war is over', 'trapped heat'). Gunakan bahasa percakapan sehari-hari yang luwes (adem, ga bikin lepek, ga engap, enak dipake gerak, jatuhnya pas di badan).
4. Gunakan titik-titik gantung (...) dan huruf dipanjangin untuk penekanan (capekkk, beneraaan, anjirrr).
5. Emoticon natural & secukupnya (maksimal 1 per post, atau tanpa emot jika sarkas/datar. Variasi: 🫠, 😭, 🥹, 💀, wkwk, kwkwk, zzzz).
6. DILARANG KERAS kata-kata bot: "racun shopee", "wajib checkout", "spill racun", "link di bio", "murce bgt say", "halo guys".
7. Post utama TANPA LINK SAMA SEKALI (zero outbound link). Ajakan ke reply harus tersirat dan santai (contoh: "link toko ku taro reply ya", "yg mau link tokonya ada di reply").

Output HARUS dalam format JSON murni:
{{
  "main_post": "Teks post utama sesuai aturan di atas",
  "reply_post": "beli di official store ini: [link affiliate]"
}}
"""

def extract_content_from_resp(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if raw_text.startswith("{") and not raw_text.startswith("data:"):
        try:
            d = json.loads(raw_text)
            if "choices" in d and len(d["choices"]) > 0:
                c = d["choices"][0].get("message", {}).get("content", "")
                if c:
                    return c
        except Exception:
            pass

    accumulated = ""
    for line in raw_text.splitlines():
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                chunk = json.loads(line[6:])
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content") or ""
                accumulated += content
            except Exception:
                continue
    return accumulated if accumulated else raw_text

def generate_threads_copy(product_name: str, price: str, highlights: str, affiliate_link: str, model: str = DEFAULT_MODEL) -> dict:
    angle = random.choice(ANGLES)
    length_style = random.choice(LENGTHS)
    hook_style = random.choice(HOOKS)
    
    system_prompt = build_system_prompt(angle, length_style, hook_style)
    prompt = f"""Buatkan 1 konten Threads untuk produk berikut:
- Produk: {product_name}
- Kisaran Harga: {price}
- Highlight / Detail Realistis: {highlights}
- Link Affiliate: {affiliate_link}

Kembalikan HANYA JSON sesuai format."""

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.85
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{NINEROUTER_URL}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {NINEROUTER_KEY}",
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        text = extract_content_from_resp(raw)

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            res = json.loads(match.group(0))
        else:
            res = json.loads(text)

    # Tambahkan prompt gambar otomatis berbasis persona terkunci
    res["image_prompt"] = build_image_prompt(product_name, highlights)
    return res

def build_image_prompt(product_name: str, highlights: str) -> str:
    return (
        f"Candid full-body mirror selfie taken with an iPhone in a real Indonesian bedroom. "
        f"Subject: A slim petite Indonesian young woman (~158cm) with natural warm olive skin tone. "
        f"She holds up a smartphone with a matte black phone case in front of her face, completely blocking her face and eyes (faceless mirror selfie). "
        f"Wearing: deep espresso brown messy wavy hair over shoulders (or neatly draped neutral pashmina), wearing {product_name} ({highlights}). "
        f"Environment: Real Indonesian bedroom with white glossy ceramic tile floor, wooden two-door wardrobe with small luggage on top, clothes hanging behind door, laundry basket on floor, and bed on the right. "
        f"Lighting & Camera: Authentic iPhone mobile snapshot, natural daylight from side window, realistic fabric drape and wrinkles, natural ISO grain, real life photo aesthetic --ar 3:4 --no 3d render, cartoon, plastic skin, extra limbs"
    )

def build_warmup_image_prompt(text: str, slot: str = "Siang") -> dict:
    import random
    
    # 50% kemungkinan: post murni teks tanpa gambar
    if random.random() >= 0.5:
        return None

    # Kunci Face DNA agar identitas orangnya selalu sama
    face_dna = (
        "Subject: An attractive 21-year-old Indonesian university student with round youthful cheeks, "
        "cute baby face, soft oval facial structure, natural warm golden-olive skin tone, and dark brown almond eyes. "
        "Hair/Hijab: Messy deep espresso wavy hair with wispy curtain bangs (or loosely draped casual black jersey pashmina). "
    )

    # Deteksi konteks teks
    text_lower = text.lower()
    is_outfit = any(w in text_lower for w in [
        "celana", "kulot", "kemeja", "dress", "gamis", "rok", "baju", 
        "linen", "kaos", "t-shirt", "outfit", "cuttingan", "bahan", "lecek", "nerawang", "fabric"
    ])
    is_panas_jalan = any(w in text_lower for w in ["panas", "siang", "jalan", "macet", "makan siang", "keluar"])

    if is_outfit:
        scene_choices = [
            {
                "prompt": (
                    f"Candid full-body mirror selfie taken with an iPhone in a real Indonesian bedroom. {face_dna}"
                    "She holds up a smartphone with a matte black phone case in front of her face, completely blocking her face and eyes (faceless mirror selfie). "
                    "Wearing: casual comfortable daily wear related to the discussion, natural fabric drape. "
                    "Environment: Real Indonesian bedroom with white glossy ceramic tile floor, wooden two-door wardrobe with small luggage on top, clothes hanging behind door, laundry basket on floor, and bed on the right. "
                    "Lighting & Camera: Authentic iPhone mobile snapshot, natural daylight from side window, realistic fabric drape and wrinkles, natural ISO grain, real life photo aesthetic --ar 3:4 --no 3d render, cartoon, plastic skin, extra limbs"
                ),
                "ref_note": "Tanpa Referensi — Muka Ketutup HP"
            },
            {
                "prompt": (
                    f"A candid casual mirror selfie in an aesthetic local coffee shop restroom. {face_dna}"
                    "Holding an iPhone with a dark case at chest level showing her full outfit and face with a subtle playful smirk. "
                    "Wearing: chic oversized neutral shirt or casual knit top matching the post discussion. "
                    "Environment: Minimalist cafe restroom with backlit arched mirror, warm terrazzo or soft concrete walls, brass faucet visible. "
                    "Lighting & Camera: Soft ambient warm lighting, authentic smartphone mirror reflection, unedited casual social media photo --ar 3:4 --no 3d render, corporate formal, plastic skin"
                ),
                "ref_note": "Wajib Pakai Foto Referensi Anchor"
            }
        ]
        return random.choice(scene_choices)

    elif is_panas_jalan or slot.lower() == "siang":
        scene_choices = [
            {
                "prompt": (
                    f"A candid casual desk photo taken from a smartphone during daytime work or study break. {face_dna}"
                    "She is sitting at her desk in a simple comfortable casual crewneck or t-shirt, resting chin on hand with a relatable relaxed half-smile. "
                    "Environment: Indonesian room or modern workspace with bright natural window daylight, laptop, cold iced tea or iced coffee glass on desk. "
                    "Lighting & Camera: Authentic smartphone snapshot, bright soft natural daylight, genuine skin texture, unedited Gen-Z mobile photo --ar 4:3 --no 3d render, plastic skin, nighttime, cgi"
                ),
                "ref_note": "Wajib Pakai Foto Referensi Anchor"
            },
            {
                "prompt": (
                    f"A candid casual outdoor snapshot sitting at a shaded terrace cafe in Indonesia. {face_dna}"
                    "Holding an iced matcha glass with a straw on a wooden table, wearing a relaxed casual daily outfit, looking away slightly with a natural candid laugh. "
                    "Environment: Outdoor cafe terrace with tropical potted plants and warm natural ambient daylight. "
                    "Lighting & Camera: Natural daylight, soft depth of field, authentic smartphone camera quality, unedited Gen-Z aesthetic --ar 3:4 --no 3d render, plastic skin, heavy makeup"
                ),
                "ref_note": "Wajib Pakai Foto Referensi Anchor"
            }
        ]
        return random.choice(scene_choices)

    else:
        # Waktu Malam
        scene_choices = [
            {
                "prompt": (
                    f"A candid late-night selfie taken on an Apple MacBook Photo Booth webcam. {face_dna}"
                    "Wearing: dark oversized casual crewneck sweatshirt. "
                    "Pose: Resting chin on left hand or making a subtle cute peace sign near cheek, looking directly into laptop webcam with an expressive natural half-smile. "
                    "Environment: Dim cozy bedroom, warm yellow fairy string lights on wall, desk with open notebook and tumbler in foreground. "
                    "Lighting & Camera: Soft cool glow from laptop screen contrasting with warm ambient room lights, authentic MacBook webcam sensor grain, slight motion softness, unedited 2024 Gen-Z photo aesthetic --ar 4:3 --no 3d render, plastic skin, dslr sharpness, mature 30yo woman, cgi"
                ),
                "ref_note": "Wajib Pakai Foto Referensi Anchor"
            },
            {
                "prompt": (
                    f"A candid casual desk photo taken from a laptop webcam during evening study/work. {face_dna}"
                    "She is leaning back in her desk chair holding a ceramic mug with both hands, soft friendly gaze towards screen. "
                    "Environment: Indonesian room interior at night, warm table lamp light, simple bedroom setting in background. "
                    "Lighting & Camera: Authentic webcam grain, gentle screen reflection on eyes, casual authentic lifestyle moment --ar 4:3 --no 3d render, cgi, airbrushed skin"
                ),
                "ref_note": "Wajib Pakai Foto Referensi Anchor"
            }
        ]
        return random.choice(scene_choices)

if __name__ == "__main__":
    for i in range(3):
        print(f"\n--- TEST GENERATE #{i+1} ---")
        res = generate_threads_copy(
            product_name="Gamis Crinkle Airflow Loose Fit",
            price="Rp75.000",
            highlights="bahan ga gampang lecek tanpa disetrika, adem, wudhu friendly lengan karet, ga nerawang",
            affiliate_link="https://s.shopee.co.id/sample123"
        )
        print("MAIN POST:\n", res.get("main_post"))
        print("REPLY POST:\n", res.get("reply_post"))

import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, timedelta
import hashlib

# --- ⚙️ DEĞİŞTİRİLEBİLİR AYARLAR ---
LIG_SAYISI = 3
LIG_ISIMLERI = ["1. Lig", "2. Lig", "3. Lig"]
LIG_SURESI_GUN = 7
LIG_BASLANGIC_GUNU = 0  # 0 = Pazartesi
LIG_BASLANGIC_SAAT = 0
GALIBIYET_PUANI = 3
BERABERLIK_PUANI = 1
KAC_KISI_YUKSELECEK = 1  # Her ligden kaç kişi bir üst lige çıkacak
KAC_KISI_DUSECEK = 1     # Her ligden kaç kişi bir alt lige düşecek

# --- 1. SUPABASE BAĞLANTI AYARLARI ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

def hash_sifre(sifre: str) -> str:
    return hashlib.sha256(sifre.encode()).hexdigest()

@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase()

# --- YARDIMCI FONKSİYONLAR ---
@st.cache_data(ttl=10)
def veri_cek(tablo_adi):
    try:
        res = supabase.table(tablo_adi).select("*").execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=30)
def leaderboard_get():
    res = supabase.table("users_public").select("*").execute()
    return pd.DataFrame(res.data)

def lig_baslangic_bul():
    simdi = datetime.now()
    gun_farki = (simdi.weekday() - LIG_BASLANGIC_GUNU) % 7
    return (simdi - timedelta(days=gun_farki)).replace(hour=LIG_BASLANGIC_SAAT, minute=0, second=0, microsecond=0)

def kalan_sure_format(td):
    gun = td.days
    saat, remainder = divmod(td.seconds, 3600)
    dakika, saniye = divmod(remainder, 60)
    if gun > 0: return f"{gun}g {saat}s {dakika}dk"
    return f"{saat}s {dakika}dk"

def kalan_sure_hesapla():
    baslangic = lig_baslangic_bul()
    bitis_zamani = baslangic + timedelta(days=LIG_SURESI_GUN)
    kalan = bitis_zamani - datetime.now()
    if kalan.total_seconds() <= 0: return "Sezon Bitti!"
    return kalan_sure_format(kalan)

# --- OTOMATİK LİG VE MAÇ SİSTEMİ ---
def sessiz_otomasyon():
    df_matches = veri_cek("matches")
    
    if df_matches.empty:
        supabase.table("league").delete().neq("match_id", "0").execute()
        
        df_users = veri_cek("users")
        if df_users.empty: return

        df_users = df_users.sort_values(by=["points", "name"], ascending=[False, True]).reset_index(drop=True)
        n = len(df_users)
        dagilim = [n // LIG_SAYISI] * LIG_SAYISI
        for i in range(n % LIG_SAYISI): dagilim[-(i+1)] += 1

        bas = 0
        guncel_user_listesi = []
        for i, miktar in enumerate(dagilim, 1):
            grup = df_users.iloc[bas:bas+miktar]
            lig_adi = LIG_ISIMLERI[i-1]
            for _, u in grup.iterrows():
                supabase.table("users").update({"league": lig_adi, "points": 0}).eq("name", u['name']).execute()
                u['league'] = lig_adi
                u['points'] = 0
                guncel_user_listesi.append(u)
            bas += miktar
        
        yeni_maclar = []
        lig_baslangici = lig_baslangic_bul()
        final_df = pd.DataFrame(guncel_user_listesi)
        
        for i, lig_adi in enumerate(LIG_ISIMLERI, 1):
            oyuncular = final_df[final_df['league'] == lig_adi]['name'].tolist()
            if len(oyuncular) < 2: continue
            
            oyuncu_listesi = oyuncular.copy()

            # Tek sayıysa BYE ekle
            bye_var = False
            if len(oyuncu_listesi) % 2 == 1:
                oyuncu_listesi.append("BYE")
                bye_var = True

            oyuncu_sayisi = len(oyuncu_listesi)

            # TUR SAYISI
            if bye_var:
                tur_sayisi = oyuncu_sayisi
            else:
                tur_sayisi = oyuncu_sayisi - 1

            # TUR BAŞI SÜRE
            mac_basi_saat = (LIG_SURESI_GUN * 24) / tur_sayisi

            # ROUND ROBIN ALGORİTMASI
            rotasyon = oyuncu_listesi[:]

            # 🔹 Her oyuncu her oyuncuyla bir maç oynayacak
            for j in range(len(oyuncular)):
                for k in range(j + 1, len(oyuncular)):
                    p1 = oyuncular[j]
                    p2 = oyuncular[k]

                    # Başlangıç ve bitiş zamanı
                    start_time = lig_baslangici + timedelta(hours=len(yeni_maclar)*2)  # her maç 2 saat aralıklı
                    deadline = start_time + timedelta(hours=2)

                    m_id = f"{str(i).zfill(2)}{str(j+1).zfill(2)}{p1}vs{p2}"

                    yeni_maclar.append({
                        "match_id": m_id,
                        "player1": p1,
                        "player2": p2,
                        "league": lig_adi,
                        "status": "Beklemede",
                        "start_time": start_time.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"),
                        "deadline": deadline.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
                    })
                      
        if yeni_maclar:
            supabase.table("matches").insert(yeni_maclar).execute()

# --- SONUÇ KAYDETME ---
def sonucu_kaydet_veya_guncelle(match_id, oyuncu_adi, yeni_skor):
    # 1️⃣ match_id format kontrolü
    if not isinstance(match_id, str) or "vs" not in match_id:
        return  # geçersiz match_id

    # 2️⃣ Skor seçeneklerini sınırla
    if yeni_skor not in ["Kazandım", "Kaybettim", "Berabere"]:
        return  # geçersiz skor

    # 3️⃣ Maç verisini çek ve yetki kontrolü
    mac = supabase.table("matches").select("player1,player2,status").eq("match_id", match_id).execute()
    if not mac.data:
        return  # maç yok

    p1, p2, status = mac.data[0]['player1'], mac.data[0]['player2'], mac.data[0]['status']

    # 4️⃣ Sadece o maçın oyuncuları işlem yapabilir
    if oyuncu_adi not in [p1, p2]:
        return

    # 5️⃣ Sadece Beklemede olan maç güncellenebilir
    if status != "Beklemede":
        return

    # 6️⃣ Mevcut sonuç var mı kontrolü
    mevcut = supabase.table("league").select("*") \
        .eq("match_id", match_id) \
        .eq("resulter_player", oyuncu_adi) \
        .execute()
    if mevcut.data:
        return

    # 7️⃣ Skoru kaydet
    supabase.table("league").upsert({
        "match_id": match_id,
        "resulter_player": oyuncu_adi,
        "result": yeni_skor
    }).execute()

    st.cache_data.clear()

# --- PUAN VE ONAY MANTIĞI ---
def mac_sonuclandir(match_id, p1, p2, final_status):
    supabase.table("matches").update({"status": final_status}).eq("match_id", match_id).execute()
    df_u = veri_cek("users")
    if "Galibiyet" in final_status:
        kazanan = final_status.split(": ")[1]
        mevcut = float(df_u[df_u['name'] == kazanan]['points'].values[0])
        supabase.table("users").update({"points": mevcut + GALIBIYET_PUANI}).eq("name", kazanan).execute()
    elif final_status == "Berabere":
        for ad in [p1, p2]:
            mevcut = float(df_u[df_u['name'] == ad]['points'].values[0])
            supabase.table("users").update({"points": mevcut + BERABERLIK_PUANI}).eq("name", ad).execute()
    st.cache_data.clear()

def sonuclari_isleme_al(match_id, deadline_str, p1, p2):
    mac = supabase.table("matches").select("status").eq("match_id", match_id).execute()

    if mac.data and mac.data[0]["status"] != "Beklemede":
        return
    bildirimler = veri_cek("league")
    ilgili = bildirimler[bildirimler['match_id'].astype(str) == str(match_id)] if not bildirimler.empty else pd.DataFrame()
    
    if len(ilgili) == 2:
        res1, res2 = ilgili.iloc[0], ilgili.iloc[1]
        s1, s2 = res1['result'], res2['result']
        status = ""
        if s1 == "Kazandım" and s2 == "Kaybettim": status = f"Galibiyet: {res1['resulter_player']}"
        elif s1 == "Kaybettim" and s2 == "Kazandım": status = f"Galibiyet: {res2['resulter_player']}"
        elif s1 == "Berabere" and s2 == "Berabere": status = "Berabere"
        
        if status: mac_sonuclandir(match_id, p1, p2, status)
        else: supabase.table("matches").update({"status": "HATA: UYUMSUZ"}).eq("match_id", match_id).execute()
    
    elif deadline_str and datetime.now() > datetime.fromisoformat(deadline_str):
        if len(ilgili) == 1:
            res = ilgili.iloc[0]
            status = f"Galibiyet: {res['resulter_player']}" if res['result'] == "Kazandım" else "Berabere"
            mac_sonuclandir(match_id, p1, p2, status)
        else:
            supabase.table("matches").update({"status": "İPTAL"}).eq("match_id", match_id).execute()

def tie_break_sirala(lig_df, df_matches):

    result = []
    i = 0

    while i < len(lig_df):

        same = [lig_df.iloc[i]]
        j = i + 1

        while j < len(lig_df) and lig_df.iloc[j]['points'] == lig_df.iloc[i]['points']:
            same.append(lig_df.iloc[j])
            j += 1

        if len(same) == 1:
            result.append(same[0])
        else:

            mini = pd.DataFrame(same)
            players = mini['name'].tolist()

            mini_points = {p:0 for p in players}

            for _, m in df_matches.iterrows():

                p1 = m['player1']
                p2 = m['player2']

                if p1 in players and p2 in players:

                    status = m['status']

                    if "Galibiyet" in status:
                        winner = status.split(": ")[1]
                        mini_points[winner] += GALIBIYET_PUANI

                    elif status == "Berabere":
                        mini_points[p1] += BERABERLIK_PUANI
                        mini_points[p2] += BERABERLIK_PUANI

            mini["mini_points"] = mini["name"].map(mini_points)

            mini = mini.sort_values(
                by=["mini_points","name"],
                ascending=[False,True]
            )

            result.extend(mini.to_dict("records"))

        i = j

    return pd.DataFrame(result)

def ligleri_guncelle():
    df_users = veri_cek("users")
    df_matches = veri_cek("matches")
    if df_users.empty or df_matches.empty: return

    for i, lig_adi in enumerate(LIG_ISIMLERI):
        lig_kisileri = df_users[df_users['league'] == lig_adi].copy()
        if lig_kisileri.empty: continue

        # Puanlara göre sırala
        lig_kisileri = lig_kisileri.sort_values(by=["points","name"], ascending=[False,True])
        lig_kisileri = tie_break_sirala(lig_kisileri, df_matches)

        # Aynı puanlılar varsa kendi aralarındaki maçlara bak
        for j in range(len(lig_kisileri)-1):
            if lig_kisileri.loc[j, 'points'] == lig_kisileri.loc[j+1, 'points']:
                p1 = lig_kisileri.loc[j, 'name']
                p2 = lig_kisileri.loc[j+1, 'name']
                # İkili maçlar
                df_results = veri_cek("league")

                df_matches = veri_cek("matches")

                karsilasmalar = df_matches[
                    ((df_matches['player1'] == p1) & (df_matches['player2'] == p2)) |
                    ((df_matches['player1'] == p2) & (df_matches['player2'] == p1))
                ]

                p1_skor = 0
                p2_skor = 0

                for _, m in karsilasmalar.iterrows():
                    status = m['status']

                    if "Galibiyet" in status:
                        kazanan = status.split(": ")[1]
                        if kazanan == p1:
                            p1_skor += GALIBIYET_PUANI
                        elif kazanan == p2:
                            p2_skor += GALIBIYET_PUANI

                    elif status == "Berabere":
                        p1_skor += BERABERLIK_PUANI
                        p2_skor += BERABERLIK_PUANI
                        # Swap sıralama
                        lig_kisileri.loc[[j, j+1]] = lig_kisileri.loc[[j+1, j]].values

        # Yükselme / düşme işlemi (ilk lig ve son lig hariç)
        if i > 0:  # düşme
            dusenler = lig_kisileri.tail(KAC_KISI_DUSECEK)
            for u in dusenler['name']:
                supabase.table("users").update({"league": LIG_ISIMLERI[i-1]}).eq("name", u).execute()
        if i < LIG_SAYISI-1:  # yükselme
            yukselenler = lig_kisileri.head(KAC_KISI_YUKSELECEK)
            for u in yukselenler['name']:
                supabase.table("users").update({"league": LIG_ISIMLERI[i+1]}).eq("name", u).execute()

def sezonu_bitir_ve_yenile():

    df_users = veri_cek("users")

    if df_users.empty:
        return

    # her lig için işlem yap
    for i, lig_adi in enumerate(LIG_ISIMLERI):

        lig_kisileri = df_users[df_users['league'] == lig_adi].copy()

        if lig_kisileri.empty:
            continue

        lig_kisileri = lig_kisileri.sort_values(by="points", ascending=False).reset_index(drop=True)

        # DÜŞME
        if i > 0:

            dusenler = lig_kisileri.tail(KAC_KISI_DUSECEK)

            for u in dusenler['name']:
                supabase.table("users").update({
                    "league": LIG_ISIMLERI[i-1]
                }).eq("name", u).execute()

        # YÜKSELME
        if i < LIG_SAYISI-1:

            yukselenler = lig_kisileri.head(KAC_KISI_YUKSELECEK)

            for u in yukselenler['name']:
                supabase.table("users").update({
                    "league": LIG_ISIMLERI[i+1]
                }).eq("name", u).execute()

    # PUAN RESET
    supabase.table("users").update({"points": 0}).neq("name", "").execute()

    # MAÇ RESET
    supabase.table("matches").delete().neq("match_id", "0").execute()

    # SONUÇ RESET
    supabase.table("league").delete().neq("match_id", "0").execute()

    # cache temizle
    st.cache_data.clear()

# --- GİRİŞ VE PANEL ---
sessiz_otomasyon()

if kalan_sure_hesapla() == "Sezon Bitti!":

    df_matches = veri_cek("matches")

    # sadece bir kere çalışsın
    if not df_matches.empty:
        ligleri_guncelle()
        sezonu_bitir_ve_yenile()
        st.rerun()

if 'giris_yapildi' not in st.session_state:
    st.session_state['giris_yapildi'] = False

if not st.session_state['giris_yapildi']:
    st.title("♟️ Satranç Ligi a")

    isim = st.text_input("Kullanıcı Adı")
    sifre = st.text_input("Şifre", type="password")

    if st.button("Giriş Yap", use_container_width=True):

        if not isim or not sifre:
            st.warning("Boş bırakma")
            st.stop()

        isim = isim.strip()
        sifre = sifre.strip()

        # 🔥 TÜM KULLANICILARI ÇEK
        res = supabase.table("users").select("name,password,league").execute()
        if not res.data:
            st.error("Veritabanı hatası veya kullanıcı yok")
            st.stop()

        user = None

        for u in res.data:
            if u["name"].strip().lower() == isim.strip().lower():
                user = u
                break

        if user:
            if user["password"] == hash_sifre(sifre):
                st.session_state.update({
                    'giris_yapildi': True,
                    'kullanici_adi': user["name"],
                    'lig': str(user['league'])
                })
                st.rerun()
            else:
                st.error("Şifre yanlış.")
        else:
            st.error("Kullanıcı bulunamadı.")

else:
    with st.sidebar:
        st.header("🏆 Liderlik Tablosu")
        secilen_lig = st.selectbox("Ligi Görüntüle:", LIG_ISIMLERI, index=LIG_ISIMLERI.index(st.session_state['lig']))
        df_all = leaderboard_get()        
        if not df_all.empty:
            lt = df_all[df_all['league'] == secilen_lig].sort_values(by=["points", "name"], ascending=[False, True]).reset_index(drop=True)
            lt.index += 1
            st.table(lt[['name', 'points']].rename(columns={'name': 'Oyuncu', 'points': 'Puan'}))
        st.divider()
        st.write(f"⌛ **Sezon Bitişine:**\n### {kalan_sure_hesapla()}")

    c1, c2 = st.columns([4, 1])
    c1.subheader(f"Merhaba {st.session_state['kullanici_adi']} | {st.session_state['lig']}")
    if c2.button("Çıkış"):
        st.session_state['giris_yapildi'] = False
        st.rerun()
    st.divider()

    res = supabase.table("matches").select("*").or_(
        f"player1.eq.'{st.session_state['kullanici_adi']}',player2.eq.'{st.session_state['kullanici_adi']}'"
    ).execute()

    df_m = pd.DataFrame(res.data)  # <- burada df_m oluşturuyoruz
    if not df_m.empty:
        # BYE maçlarını ve Beklemede olmayan maçları filtrele
        df_m = df_m[
            (df_m['player1'] != "BYE") &
            (df_m['player2'] != "BYE") &
            (df_m['status'] == "Beklemede")
    ]

    # BYE maçlarını filtrele
    bm = df_m[
        (df_m['player1'] == st.session_state['kullanici_adi']) |
        (df_m['player2'] == st.session_state['kullanici_adi'])
    ].sort_values(by="deadline").reset_index(drop=True)

    st.write("### 📅 Fikstürün")
    df_bildirimler = veri_cek("league")
    
    aktif_mac_var = False

    df_all_matches = veri_cek("matches")

    bekleyen_maclar = df_all_matches[df_all_matches['status'] == "Beklemede"]
    
    if not bekleyen_maclar.empty:
        for _, m in bekleyen_maclar.iterrows():
            sonuclari_isleme_al(
                m['match_id'],
                m['deadline'],
                m['player1'],
                m['player2']
            )

    for _, row in bm.iterrows():
        rakip = row['player2'] if row['player1'] == st.session_state['kullanici_adi'] else row['player1']
        rakip_phone = ""
        if not df_all.empty:
            phone_row = df_all[df_all['name'] == rakip]
            if not phone_row.empty and 'phone' in phone_row.columns:
                rakip_phone = phone_row.iloc[0]['phone']
        durum = str(row['status']).strip()
        if durum != "Beklemede":
            continue

        m_id = str(row['match_id'])
        round_no = int(m_id[2:4])
        dl_str = row['deadline']
        start_str = row.get('start_time')
        if not start_str:
            continue
        start_date = datetime.fromisoformat(start_str)
        dl_date = datetime.fromisoformat(dl_str)
        kalan_sure = dl_date - datetime.now()

        ligdeki_tur_maclari = df_all_matches[
            (df_all_matches['league'] == row['league']) &
            (df_all_matches['match_id'].str[2:4].astype(int) == round_no)
        ]

        # Kullanıcının o turda maçı var mı
        kullanici_bu_turda_var_mi = not ligdeki_tur_maclari[
            (ligdeki_tur_maclari['player1'] == st.session_state['kullanici_adi']) |
            (ligdeki_tur_maclari['player2'] == st.session_state['kullanici_adi'])
        ].empty

        if not kullanici_bu_turda_var_mi:
            # Bu tur BYE turu → kullanıcıya gösterme, sıradaki turu aktif göster
            continue

        onceki_turlar = df_all_matches[
            (df_all_matches['league'] == row['league']) &
            (df_all_matches['match_id'].str[2:4].astype(int) < round_no)
        ]
        now = datetime.now()

        tamamlanmamis = onceki_turlar[
            (onceki_turlar['status'] == "Beklemede") &
            (onceki_turlar['deadline'].apply(lambda x: datetime.fromisoformat(x)) > now)
        ]

        if not tamamlanmamis.empty:
            # Önceki tur bitmeden açılmasın
            with st.container(border=True):
                col_i, col_a = st.columns([2, 1])
                col_i.warning("🔒 Önceki tur bitmeden açılamaz")
                col_a.warning("⛔ Tur kilitli")
            continue  # bu maç için diğer kodları atla
        with st.container(border=True):
            col_i, col_a = st.columns([2, 1])
            
            # Sadece ilk Beklemede olan maç "Aktif" sayılır
            now = datetime.now()

            if now < start_date:

                kalan = start_date - now
                col_i.warning(f"⏳ Başlamasına: {kalan_sure_format(kalan)}")
                col_a.warning("🔒 Henüz başlamadı")

            elif start_date <= now <= dl_date and durum == "Beklemede":

                if aktif_mac_var:
                    col_i.warning("🔒 Sıradaki maçını tamamla")
                    col_a.warning("⛔ Kilitli")
                    continue

                aktif_mac_var = True

                kalan = dl_date - now
                col_i.error(f"⌛ Kalan Süre: {kalan_sure_format(kalan)}")

                zaten = not df_bildirimler[
                    (df_bildirimler['match_id'].astype(str) == m_id) &
                    (df_bildirimler['resulter_player'] == st.session_state['kullanici_adi'])
                ].empty if not df_bildirimler.empty else False

                if not zaten:
                    skor = col_a.selectbox("Sonuç:", ["-", "Kazandım", "Kaybettim", "Berabere"], key=f"s_{m_id}")
                    if col_a.button("Kaydet", key=f"b_{m_id}"):

                        if skor != "-":
                            sonucu_kaydet_veya_guncelle(m_id, st.session_state['kullanici_adi'], skor)
                            sonuclari_isleme_al(m_id, dl_str, row['player1'], row['player2'])
                            st.rerun()
                else:
                    col_a.info("⌛ Bekleniyor...")

            else:

                col_i.warning("⏱ Süre doldu")

            col_i.write(f"⚔️ **Rakip:** {rakip} | 📞 {rakip_phone}  \n📌 **Durum:** `{durum}`")

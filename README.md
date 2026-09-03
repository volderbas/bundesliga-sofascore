# Bundesliga Merkezi — SofaScore (curl_cffi)

Bundesliga ve 2. Bundesliga maçlarını **lokalde** takip etmek için hazırlanmış bağımsız uygulama.
SofaScore API'sine `curl_cffi` ile **gerçek Chrome/Safari TLS parmak izi taklit ederek** istek atar.

## Kurulum & Çalıştırma

**macOS / Linux**
```bash
chmod +x start.sh
./start.sh
```

**Windows**: `start.bat` dosyasına çift tıklayın.

**Manuel**
```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Tarayıcı otomatik açılır: <http://127.0.0.1:8777>
Port değiştirmek için: `PORT=9000 python run.py`

## Özellikler

- **Canlı maçlar** (30 sn otomatik yenileme), **bugün**, **yaklaşan 8 gün**, **bitmiş maçlar**
- **Puan durumu** (her iki lig)
- Maç detayı:
  - Skor, ilk yarı skoru, durum, hafta, stat, şehir, hakem, seyirci, teknik direktörler
  - **İlk 11** (diziliş, forma no, mevki, kaptan, SofaScore reytingi)
  - **Yedekler** ve **eksik oyuncular** (sakat/cezalı)
  - **Girenler / çıkanlar** (oyuncu değişiklikleri)
  - **Goller** (penaltı / kendi kalesine / asist) ve **kartlar** (sarı, ikinci sarı, kırmızı + sebep)
  - **Olay akışı** (dakika dakika: devreler, uzatmalar, VAR kararları)
  - **İstatistikler** (topla oynama, şutlar, pas isabeti, faul, korner… bar grafiklerle)

## Ban yememek için alınan önlemler

| Önlem | Açıklama |
|---|---|
| TLS/JA3 taklidi | `curl_cffi` ile chrome120/123/124/131, safari17, edge101 profilleri |
| Profil rotasyonu | Her 120 istekte bir ve 403/429 alındığında otomatik profil değişimi |
| Rate limit | İstekler arası min. 0.9 sn + rastgele jitter (insansı davranış) |
| Retry + backoff | 403/429/503'te üstel bekleme (2^n + rastgele) ile 4 deneme |
| Cache (TTL) | Canlı veri 12–20 sn, sezon/puan durumu 15 dk–6 saat önbellekte |
| Gerçekçi başlıklar | Referer/Origin/Sec-Fetch/Accept-Language başlıkları tarayıcıyla aynı |
| Paralel sınırı | En fazla 6 eşzamanlı istek |

`POST /api/cache/clear` ile önbelleği temizleyip parmak izini elle yenileyebilirsiniz.

## API uçları (kendi scriptleriniz için)

```
GET  /api/leagues
GET  /api/live
GET  /api/upcoming?days=7
GET  /api/date/2026-09-05
GET  /api/league/{bundesliga|bundesliga2}/events?kind=last|next&page=0
GET  /api/league/{lig}/round/{hafta}
GET  /api/league/{lig}/standings
GET  /api/match/{event_id}      # ilk11, yedek, olaylar, istatistik, h2h, momentum
POST /api/cache/clear
```

Yalnızca kişisel/eğitim amaçlı kullanın; SofaScore kullanım koşullarına uyun.

# uav-sim: Preflight kodunu donanımsız deneme ortamı

Pi, Cube ve kamera elinde yokken yazdığın **preflight** kodunu kendi bilgisayarında
(Windows, Linux, Mac) denemen için hazırlandı. Senin kodunun parçası değil:
karşısındaki "uçak" rolünü oynar. Preflight kodunu ayrı bir klasörde sen yazarsın.

## Gerçek sistem ve simülasyon

| Gerçekte | Simülasyonda |
|---|---|
| Cube Orange+ (ArduPlane) | `python -m uav_sim` (sahte Cube) |
| Pi GPIO14/15 ↔ Cube TELEM2 (seri, 921600 baud) | UDP port **14560**. Kodun `udpin:0.0.0.0:14560` adresine bağlanır |
| Cube TELEM1 ↔ SiK radyo ↔ Mission Planner | UDP port **14550**. Mission Planner'da UDP + 14550 |
| Pi Camera + `picamera2` | Sahte `picamera2` (kodun değişmez) |
| `/sys/class/thermal/thermal_zone0/temp` | `~/.uav-sim/pi/thermal_zone0/temp` (sahte Cube yazar) |
| `vcgencmd get_throttled` | `python -m uav_sim vcgencmd get_throttled` |
| Disk (`shutil.disk_usage`) | Gerçek disk, olduğu gibi çalışır |

Sahte Cube şu mesajları gönderir: `HEARTBEAT`, `SYS_STATUS`, `GPS_RAW_INT`, `RC_CHANNELS`,
`SERVO_OUTPUT_RAW`, `GLOBAL_POSITION_INT` ve `ATTITUDE`. Ayrıca sysid 255 olan sahte bir
yer istasyonu heartbeat'i de gönderir.

Şu isteklere cevap verir:
- `PARAM_REQUEST_READ` ve `PARAM_REQUEST_LIST` (sadece `SERVOx_FUNCTION/MIN/TRIM/MAX`)
- `COMMAND_LONG` içinde `DO_SET_SERVO` (183), `SET_MESSAGE_INTERVAL` (511) ve
  `REQUEST_MESSAGE` (512). Her birinin ardından `COMMAND_ACK` gelir.

**Yasak işlemleri yakalar.** Kodun ARM/DISARM, mod değiştirme, `PARAM_SET`,
`RC_CHANNELS_OVERRIDE` ya da görev yazma gönderirse sahte Cube bunu reddeder ve ekrana
büyük bir **YASAK İŞLEM** uyarısı basar. Kodunu teslim etmeden önce bu uyarının hiç
çıkmadığından emin ol.

## Kurulum (bir kere)

Python **3.11 veya üstü** gerekli (`python --version` ile kontrol et). Herhangi bir
terminalde (cmd ya da PowerShell, hangi klasörde olduğun fark etmez):

```
python -m pip install https://github.com/YUSUF-CGRC/uav-sim/archive/refs/heads/main.zip
```

Bilgisayarında git kuruluysa şu da olur: `python -m pip install git+https://github.com/YUSUF-CGRC/uav-sim`

**Güncellemek** için aynı komutu sonuna `--upgrade` ekleyerek çalıştır.

**Komutları `python -m uav_sim ...` şeklinde çalıştır.** Bu her bilgisayarda çalışır.
Kısa hali `uav-sim ...` da var, ama Windows'ta Python'un `Scripts` klasörü PATH'te değilse
"uav-sim is not recognized" hatası verir. Kurulumda "...Scripts is not on PATH" uyarısı
gördüysen ya kısa hali kullanma ya da o klasörü PATH'e ekle.

## Kullanım

```
python -m uav_sim list                 # hazır senaryoları listeler
python -m uav_sim gps_yok              # sahte Cube'u gps_yok senaryosuyla başlatır (Ctrl+C ile durur)
python -m uav_sim paths                # config dosyana yazacağın sahte Pi yolları
```

**En kolay yol: tek komut.** Preflight projenin klasöründe şunu çalıştır:

```
python -m uav_sim run gps_yok -- python -m preflight --config config_sim.toml --check-only
```

Bu komut sırasıyla şunları yapar:
1. Sahte Cube'u arka planda açar. Mesajları `[cube]` etiketiyle ekranda görürsün.
2. `--` işaretinden sonraki komutunu sahte kamera ve sahte Pi ayarlarıyla çalıştırır.
3. Komutun bitince Cube'u kapatır ve programının çıkış kodunu söyler.
4. Programın yasak bir işlem gönderdiyse sonunda büyük bir uyarı verir.

Cube mesajlarını görmek istemezsen senaryo adından önce `-q` ekle:
`python -m uav_sim run -q gps_yok -- ...`

**İki pencereyle çalışmak istersen**, örneğin Cube'u uzun süre açık tutup kodunu tekrar
tekrar çalıştırmak için:
1. Birinci pencerede `python -m uav_sim gps_yok` çalıştır.
2. İkinci pencerede `python -m uav_sim env gps_yok` yaz. Ekrana basılan `set ...` (cmd) ya da
   `$env:...` (PowerShell) satırlarını o pencereye yapıştır.
3. Kodunu ikinci pencerede istediğin kadar çalıştır.

Kodunda bağlantıyı şöyle açarsan hem gerçek seri portta hem burada çalışır. Adres
config'den gelir, gerçek Pi'de `/dev/ttyAMA0`, simülasyonda `udpin:0.0.0.0:14560`:
```python
mavutil.mavlink_connection(port, baud=baud, source_system=1, source_component=191)
```

**Mission Planner'ı da bağlayabilirsin.** Sahte Cube çalışırken sağ üstte bağlantı türünü
**UDP** seç, Connect'e bas, port olarak **14550** yaz. Uçak haritada Ankara'da görünür.
Ctrl+F ile açılan menüde **MAVLink Inspector** ile mesajları canlı izleyebilirsin. Bu ekran
1. haftanın ekran görüntüsü görevi için de işine yarar.

> Mission Planner'da parametre indirme eksik kalabilir, çünkü sahte Cube sadece servo
> parametrelerini biliyor. Bu normal.

## Kamera

Kodunda normal şekilde `from picamera2 import Picamera2` yaz. `python -m uav_sim run` (ya da
`python -m uav_sim env`) `PYTHONPATH`'i ayarladığı için Python sahte kamerayı bulur. Gerçek Pi'de
bunu yapmazsın, gerçek kütüphane çalışır. Sahte kamera sadece `uav-sim` üzerinden
çalıştırınca devreye girer, normal Python ortamını bozmaz. Sahte kamera şunları destekler:

- `Picamera2()`, `Picamera2.global_camera_info()`
- `create_video_configuration(main={"size": (1920, 1080)})` ve preview/still sürümleri
- `configure()`, `start()`, `capture_array()`, `capture_metadata()`, `stop()`, `close()`

Gerçeğe benzeyen birkaç davranışı da var:
- Kare hızı senaryodaki `fps` değerine uyar. 10 kare alıp süreyi ölçersen FPS'i
  hesaplayabilirsin.
- `close()` yapmadan ikinci kez `Picamera2()` açarsan **"Device or resource busy"** hatası
  alırsın. Bu sayede kapatmayı unuttuğun yeri yakalarsın.
- `stop()` ve `close()` birden fazla kez çağrılabilir.

## Pi sistemi (sıcaklık, throttling)

Sahte Cube çalışırken her saniye `<kullanıcı klasörü>/.uav-sim/pi/thermal_zone0/temp`
(mili-derece, örneğin `52000`) ve `.../pi/throttled` dosyalarını yazar. Tam yolları
`python -m uav_sim paths` gösterir. `vcgencmd` yerine `python -m uav_sim vcgencmd get_throttled` kullanılır. Kodunda bu yolları kodun içine gömme, config'den
oku (proje kuralı zaten bu). Simülasyon için ayrı bir config dosyası kullan. Örneği
[`config_sim.ornek.toml`](config_sim.ornek.toml) dosyasında bulabilirsin.

## Senaryolar

`python -m uav_sim list` hepsini gösterir. Dosyalar [`uav_sim/scenarios/`](uav_sim/scenarios)
klasöründe, her dosyanın başında ne beklendiği yazıyor.

| Senaryo | Ne oluyor? | Beklenen sonuç |
|---|---|---|
| `normal` | Her şey sağlıklı | HAZIR |
| `heartbeat_yok` | Cube heartbeat göndermiyor | mavlink FAIL, bağımlılar SKIP |
| `yanlis_arac` | Araç tipi QUADROTOR | mavlink FAIL |
| `gec_acilan_cube` | Cube 4 sn geç konuşmaya başlıyor | Retry sonrası OK |
| `gcs_yok` | Mission Planner heartbeat'i Pi'ye ulaşmıyor | gcs_link FAIL |
| `sensor_bozuk` | Pusula present ama healthy değil | sensors FAIL |
| `gps_yok` | fix_type=1, 3 uydu | gps FAIL |
| `gps_gec_kilitlenir` | GPS 8 sn sonra kilitleniyor | Retry/timeout ayarına göre |
| `dusuk_batarya` | 13.2 V | battery FAIL |
| `batarya_bitiyor` | Dakikada 1 V düşüyor | Ana döngü logunda görülür |
| `rc_yok` | RC alıcı yok | rc_link FAIL |
| `kamera_yok` | Kamera bulunamıyor | camera FAIL |
| `kamera_takiliyor` | `start()` sonsuza kadar takılıyor | Program kilitlenmez, camera FAIL |
| `kamera_kalitesiz` | 1280x720 @ 15 fps | camera FAIL |
| `kamera_kapanmiyor` | `close()` hata veriyor | Diğerleri yine kapanır, çıkış kodu 3 |
| `pi_sicak` | 78 °C, throttled=0x50005 | pi_system WARN, yine HAZIR |
| `arm_durumda` | Uçak ARM | Servo testi reddedilmeli |
| `servo_sapma` | Servo çıkışı 30 µs sapıyor | Servo testi adımları FAIL |
| `servo_reddediyor` | DO_SET_SERVO ACK = FAILED | Servo testi FAIL |
| `baglanti_kopuyor` | 20 sn sonra kablo "kopuyor" | Ana algoritmada ne olur? (bonus B1/B4) |
| `paket_kaybi` | Paketlerin %30'u kayboluyor | Kod sağlam kalmalı |

**Kendi senaryonu yaz.** Yeni bir `.toml` dosyası oluştur ve sadece değiştirmek istediğin
değerleri yaz. Sonra ad yerine dosya yolunu ver: `python -m uav_sim run benim.toml -- ...` Yazmadığın her şey [`uav_sim/scenario.py`](uav_sim/scenario.py) içindeki
`DEFAULTS` sözlüğünden gelir. Tüm ayarlar orada açıklamalı olarak duruyor (kanal
parametreleri, mesaj hızları, sysid ve diğerleri).

Servo kanalları ArduPlane varsayılanlarına göre ayarlı:
- 1: Aileron, 2: Elevator, 3: Throttle, 4: Rudder (otopilot yönetiyor)
- 9 ve 10: Boş kanallar (`FUNCTION=0`), görev servosu için kullanılabilir

Otopilotun yönettiği bir kanala `DO_SET_SERVO` gönderirsen ACK yine "kabul edildi" gelir,
ama `SERVO_OUTPUT_RAW`'da değer değişmez, çünkü otopilot onu her döngüde kendi yazar.
Dokümandaki "Aileron kanalına neden DO_SET_SERVO gönderemiyoruz?" sorusunun cevabını burada
kendin görebilirsin.

## Sınırlar (gerçek donanımda ayrıca dene)

- Bu bir fizik simülatörü değil. Uçak uçmaz, değerler senaryodan gelir.
- Gerçek ArduPlane çok daha fazla mesaj gönderir ve zamanlamalar farklıdır. Seri port ayarı
  (`SERIAL2_*`, `dtparam=uart0=on`, `dialout` grubu) burada test edilmez.
- Gerçek `gcs_link` davranışı Cube'un yönlendirme ayarlarına bağlıdır. Sahte Cube varsayılan
  olarak yönlendirme yapar. Gerçek Cube'da nasıl davrandığını kulüp odasında doğrulayıp
  README'ye yazman gerekiyor.
- Windows'ta SIGTERM gerçek Linux'taki gibi gönderilemez. SIGTERM (çıkış kodu 143) testini
  pytest içinde ya da Pi'de yap. Ctrl+C (SIGINT, 130) Windows'ta çalışır.

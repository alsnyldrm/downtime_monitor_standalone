# FBU Downtime Monitor - Standalone Deploy

Self-contained Docker kurulumu: **MySQL + Nginx + App** tek `docker compose` ile ayağa kalkar.

## Hızlı Kurulum

```bash
# 1. .env dosyasını oluştur
cp .env.example .env
# Gerekirse .env içindeki değerleri düzenle

# 2. Firebase service account (opsiyonel - push bildirim için)
# firebase-service-account.json dosyasını proje kök dizinine koy

# 3. Docker ile ayağa kaldır
cd docker
docker compose up -d --build

# 4. Logları kontrol et
docker compose logs -f app
```

Uygulama **http://localhost** adresinde (Nginx üzerinden) erişilebilir olacaktır.

## Servisler

| Servis | Container | Port |
|--------|-----------|------|
| MySQL 8.0 | downtime_monitor_db | 3306 |
| FastAPI App | downtime_monitor_app | 8000 (internal) |
| Nginx | downtime_monitor_nginx | 80, 443 |

## Varsayılan Admin

Uygulama ilk başlangıçta otomatik olarak admin kullanıcı oluşturur:
- **Kullanıcı:** `admin`
- **Şifre:** `admin`

> İlk girişten sonra şifreyi değiştirin!

## Durdurma / Yeniden Başlatma

```bash
cd docker

# Durdur
docker compose down

# Veritabanı dahil sil (DİKKAT: veri kaybı!)
docker compose down -v

# Yeniden başlat
docker compose up -d --build
```

## Veritabanı Yedekleme

```bash
docker exec downtime_monitor_db mysqldump -u root -pBKqD9DgxocYLfptfACjVGGBeg2KwLCwDnWbhQCEN3qeUKiPg downtimemonitor > backup.sql
```

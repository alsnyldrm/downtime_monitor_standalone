# İlerleme Durumu — FBU Downtime Monitor

## Mevcut Durum
Proje aktif ve production ortamında çalışıyor.

## Tamamlanan Özellikler
- [x] FastAPI uygulama altyapısı
- [x] SAML 2.0 (Azure AD) kimlik doğrulama
- [x] JWT tabanlı mobil API auth
- [x] Monitör CRUD (HTTP, HTTPS, Ping, Port, Keyword)
- [x] Asenkron izleme motoru (APScheduler)
- [x] Dashboard ve raporlama
- [x] Grup yönetimi
- [x] Kullanıcı yönetimi (admin/editor/readonly roller)
- [x] Firebase push bildirimleri (FCM)
- [x] Ağ araçları (DNS, Ping, Port, SSL, HTTP)
- [x] Dark/Light tema desteği
- [x] Docker Compose + Nginx deploy
- [x] Alembic migration sistemi (001-003)
- [x] Güvenlik middleware'leri (CSP, HSTS, XSS koruması)
- [x] SSRF koruması

## Devam Eden / Planlanan
- [ ] (Buraya yeni görevler eklenecek)

## Son Değişiklikler
| Tarih | Açıklama |
|-------|----------|
| — | İlk progress.md oluşturuldu |

## Notlar
- Deploy akışı: yerel commit → git push → sunucuda git pull → docker rebuild
- Tek worker zorunlu (APScheduler duplicate önlemi)
- Sunucu: 20.229.148.197

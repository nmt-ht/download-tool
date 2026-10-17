# Giấy phép của các thành phần bên thứ ba

Download Tool dùng các thành phần mã nguồn mở dưới đây. Tất cả đều **miễn phí** và **không cần xin phép** tác giả để sử dụng, kể cả cho mục đích thương mại. Các thành phần này **không được đóng gói** trong file cài đặt: bộ cài tải chúng trực tiếp từ nguồn chính thức (PyPI, python.org, nodejs.org) về máy người dùng.

## Thư viện Python (chạy chung với phần mềm)

Tất cả dùng **giấy phép dễ dãi**: cho phép dùng thương mại và không bắt công khai mã nguồn phần mềm dùng chúng.

| Thành phần | Giấy phép | Dùng để |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense (public domain) | Đọc và tải video |
| [yt-dlp-ejs](https://github.com/yt-dlp/ejs) | Unlicense, MIT, ISC | Giải mã link video YouTube |
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | MIT | Kết nối tới Dailymotion và một số trang khác |
| [requests](https://github.com/psf/requests) | Apache-2.0 | Kết nối mạng |
| [urllib3](https://github.com/urllib3/urllib3) | MIT | Kết nối mạng |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | Kết nối mạng |
| [brotli](https://github.com/google/brotli) | MIT | Giải nén dữ liệu |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 | Chứng chỉ bảo mật (chỉ ràng buộc nếu sửa chính file của certifi) |
| [pycryptodomex](https://github.com/Legrandin/pycryptodome) | BSD / Public Domain | Giải mã dữ liệu một số trang |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 hoặc BSD-3-Clause | Kiểm tra mã kích hoạt |
| [cffi](https://github.com/python-cffi/cffi), [pycparser](https://github.com/eliben/pycparser) | MIT-0, BSD-3-Clause | Thư viện nền của cryptography và curl_cffi |
| [charset-normalizer](https://github.com/jawah/charset_normalizer), [idna](https://github.com/kjd/idna) | MIT, BSD-3-Clause | Thư viện nền của requests |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause | Tìm và cung cấp ffmpeg |

**Không cài:** `mutagen` (GPL-2.0+). yt-dlp có gợi ý thư viện này, nhưng nó chỉ dùng để nhúng ảnh bìa, tính năng phần mềm không dùng. Bộ cài và bước tự cập nhật đều cố ý bỏ qua nó.

## Chương trình riêng (chạy tách biệt, phần mềm chỉ gọi tới)

| Thành phần | Giấy phép | Ghi chú |
|---|---|---|
| [Python](https://www.python.org) | PSF License | Dễ dãi |
| [Node.js](https://nodejs.org) | MIT | Dễ dãi |
| **ffmpeg** (đi kèm imageio-ffmpeg) | **GPL-3.0** | Chương trình riêng, chỉ được gọi để ghép hình và tiếng. Dùng thì không bị ràng buộc gì. Nghĩa vụ GPL (cung cấp mã nguồn ffmpeg) chỉ phát sinh nếu **bạn tự phân phối** file ffmpeg, ví dụ đóng gói nó vào file cài đặt |

> Đây là thông tin tham khảo, không phải tư vấn pháp lý. Nếu bán phần mềm thương mại ở quy mô lớn, nên hỏi luật sư về giấy phép.

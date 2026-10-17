# Download Tool

Dán link kênh, playlist hoặc 1 video (YouTube, Bilibili, Dailymotion, TikTok, Douyin, Ixigua…), phần mềm tải tất cả video về máy.

## Cách chạy

Yêu cầu: Windows + Python 3.10 trở lên. Nên có thêm Node.js hoặc Deno (yt-dlp cần để giải mã link video YouTube).

**Giao diện:** bấm đúp `run.bat`. Lần đầu chạy sẽ tự cài thư viện (yt-dlp, ffmpeg).

1. Dán link, ví dụ `https://www.youtube.com/@tenkenh`, `https://space.bilibili.com/123456/video` hoặc link 1 video bất kỳ. Xem bảng **Các trang được hỗ trợ** bên dưới.
2. Chọn thư mục lưu và chất lượng. Riêng với kênh YouTube, chọn thêm loại video (Videos / Shorts / Live).
3. Với Douyin và Ixigua: chọn **firefox** hoặc **file cookies.txt…** ở mục **Cookies**. Xem phần **Trang cần cookies** bên dưới.
4. Tuỳ chọn: tick **Chỉ tải video có giấy phép Creative Commons** (chỉ có tác dụng với YouTube).
5. Bấm **Tải về**. Nếu không bật chế độ Creative Commons, phần mềm sẽ hỏi bạn xác nhận mình có quyền tải nội dung này.

## Các trang được hỗ trợ

Phần mềm dùng thư viện yt-dlp nên đọc được hơn 1.700 trang. Các trang thường dùng (đã thử thực tế):

| Trang | Video lẻ | Cả kênh / playlist | Ghi chú |
|---|---|---|---|
| YouTube | ✅ | ✅ kênh (Videos / Shorts / Live), playlist | |
| Bilibili | ✅ | ✅ toàn bộ video của 1 tài khoản (`space.bilibili.com/…/video`), bộ sưu tập, danh sách yêu thích | Không đăng nhập thì tối đa 1080p. Gửi nhiều yêu cầu liên tục sẽ bị chặn tạm thời (mã 412 / 352): phần mềm tự dừng và hướng dẫn. Nên dùng cookies Firefox và tải 1 video cùng lúc |
| Dailymotion | ✅ | ✅ kênh, playlist | |
| TikTok | ✅ | ⚠️ qua link 1 video | Trang tài khoản thường không đọc được. Dán link **1 video** của tài khoản và tick ô **TikTok: tải cả kênh**. Cách này chạy được với nhiều tài khoản (đã thử: 76 video), nhưng không phải tất cả |
| Douyin | ✅ cần cookies | ❌ | Dán link từng video `douyin.com/video/…` |
| Ixigua | ✅ cần cookies | ❌ | |
| Kuaishou | ❌ | ❌ | yt-dlp không hỗ trợ trang này |

Các trang khác (Vimeo, Facebook, Weibo, Youku, iQiyi, AcFun…) cứ dán link vào thử. Nếu trang không hỗ trợ, phần mềm sẽ báo lỗi kèm lý do.

### Trang cần cookies (Douyin, Ixigua)

Các trang này chỉ cho tải khi có cookies của trình duyệt. **Không cần đăng nhập.**

**Cách 1 – Firefox:**
1. Mở **Firefox**, vào trang đó (ví dụ douyin.com) và xem 1 video bất kỳ.
2. Đóng Firefox.
3. Trong phần mềm, chọn **firefox** ở mục **Cookies**, rồi bấm **Tải về**.

**Cách 2 – file cookies.txt (dùng được với mọi trình duyệt):**
1. Cài tiện ích **Get cookies.txt LOCALLY** cho Chrome, Edge hoặc Firefox.
2. Mở trang cần tải (ví dụ douyin.com), bấm vào tiện ích rồi chọn **Export**. Bạn sẽ có một file `.txt`.
3. Trong phần mềm, chọn **file cookies.txt…** ở mục **Cookies**, chọn file vừa xuất, rồi bấm **Tải về**.

Trên Windows, phần mềm không đọc trực tiếp được cookies của Chrome và Edge (Windows khoá chúng). Vì vậy nên dùng Firefox hoặc cách 2.

Phần mềm chỉ dùng **bản sao tạm** của file cookies và xoá bản sao đó khi tải xong. File gốc của bạn không bị sửa. File cookies chứa thông tin đăng nhập nên **không gửi file này cho người khác**.

**Dòng lệnh:**

```bash
run.bat https://www.youtube.com/@tenkenh -o D:\Videos -q 1080 --cc-only
```

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `-o` | Thư mục lưu (mặc định `~/Downloads/YouTube`) |
| `-q` | `best`, `2160`, `1440`, `1080`, `720`, `480`, `360`, `audio` (MP3) |
| `--shorts` / `--live` | Tải cả Shorts / video Live đã phát |
| `--no-videos` | Bỏ tab Videos thường |
| `--subs` | Tải phụ đề tiếng Việt và tiếng Anh |
| `--cookies-from-browser firefox` | Dùng cookies của trình duyệt: bắt buộc cho Douyin / Ixigua; cũng dùng cho video giới hạn tuổi hoặc dành cho hội viên |
| `--cookies cookies.txt` | Dùng file cookies.txt (xuất bằng tiện ích "Get cookies.txt LOCALLY") |
| `--tiktok-channel` | Với link 1 video TikTok: tải cả kênh của tài khoản đăng video đó |
| `--cc-only` | Chỉ tải video có giấy phép Creative Commons, bỏ qua các video khác |
| `--i-have-rights` | Xác nhận bạn có quyền tải nội dung này, bỏ qua câu hỏi xác nhận (dùng khi chạy tự động) |
| `--parallel 2` | Số video tải cùng lúc: `1`, `2` hoặc `3` (mặc định `2`) |
| `--sleep 2-5` | Nghỉ ngẫu nhiên giữa các video, tính bằng giây (mặc định `2-5`, `0` = không nghỉ) |
| `--min-free-gb 2` | Dừng khi ổ đĩa còn trống ít hơn mức này (mặc định 2 GB) |

Nếu không có `--cc-only` hoặc `--i-have-rights`, chương trình sẽ hỏi xác nhận trước khi tải.

## Kết quả

```
<thư mục lưu>/<Tên kênh YouTube>/          ← link kênh YouTube
<thư mục lưu>/<Tên trang> - <Tên kênh>/    ← các link khác, vd. "Bilibili - 某UP主"
    Videos/2024-05-01 - Tiêu đề [videoId].mp4
    Shorts/...   (chỉ kênh YouTube)
    Live/...     (chỉ kênh YouTube)
    downloaded.txt   ← danh sách video đã tải xong
    failed.txt       ← video lỗi (nếu có)
    ATTRIBUTION.txt  ← chế độ CC: tiêu đề, tác giả, link, giấy phép của từng video
```

## Tốc độ tải

Mặc định chương trình tải **2 video cùng lúc**. Đo thực tế trên mạng 55 Mbps, tải 2 video cùng lúc đạt trung bình khoảng 11 MB/s, gần gấp đôi so với tải từng video một (khoảng 6 MB/s), và tốc độ ổn định hơn. Tải 3 video cùng lúc không nhanh hơn 2, vì YouTube giới hạn tốc độ cho mỗi kết nối, mà lại dễ bị chặn hơn.

Có thể đổi ở ô **Số video tải cùng lúc** (dòng lệnh: `--parallel`):
- **1**: chậm nhất nhưng ít bị chặn nhất. Nên dùng khi vừa bị YouTube chặn.
- **2**: mặc định, khuyên dùng.
- **3**: chỉ nên dùng khi mạng rất mạnh.

Muốn nhanh hơn nữa thì chọn chất lượng thấp hơn: 720p có dung lượng chỉ bằng khoảng một nửa 1080p.

## Các cơ chế tự bảo vệ

| Cơ chế | Cách hoạt động |
|---|---|
| **Nghỉ giữa các video** | Mỗi luồng tải nghỉ ngẫu nhiên 2–5 giây trước video tiếp theo để không gửi yêu cầu dồn dập. Video đã có sẵn thì không nghỉ. Bấm Dừng vẫn có tác dụng ngay cả khi đang nghỉ. |
| **Tự dừng khi bị YouTube chặn** | Gặp lỗi 429 hoặc yêu cầu xác minh "not a bot" thì dừng ngay, không thử tiếp các video còn lại (thử tiếp chỉ làm thời gian bị chặn kéo dài). Đợi vài giờ rồi chạy lại. |
| **Kiểm tra dung lượng ổ đĩa** | Trước mỗi video, tool ước lượng dung lượng cần (gấp đôi dung lượng video, vì file tạm và file ghép cùng tồn tại) và luôn chừa lại 2 GB. Không đủ chỗ thì dừng và báo cần bao nhiêu. |
| **Bỏ qua video đang/sắp phát trực tiếp** | Video đang phát, sắp phát, sắp công chiếu, hoặc vừa phát xong mà YouTube chưa xử lý xong sẽ bị bỏ qua. Lần chạy sau, khi buổi phát đã kết thúc, video sẽ được tải. |

Khi tool dừng vì bị chặn hoặc ổ đĩa đầy, giao diện sẽ hiện hộp thông báo lý do. Bản dòng lệnh thoát với mã `3`.

## Chế độ Creative Commons

Khi bật chế độ này, phần mềm đọc giấy phép của từng video và chỉ tải video ghi *Creative Commons*. Các video khác bị bỏ qua và được đếm riêng trong phần tổng kết.

- YouTube chỉ có giấy phép CC BY (Ghi công tác giả). Khi dùng lại video, bạn phải ghi tên tác giả. Thông tin cần ghi có sẵn trong `ATTRIBUTION.txt`.
- Video không phải CC sẽ không vào `downloaded.txt`, nên lần chạy sau vẫn được kiểm tra lại. Nếu chủ kênh đổi giấy phép sang CC, video sẽ được tải.

- **Tải tiếp được:** dừng giữa chừng hoặc chạy lại sau, video đã tải sẽ được bỏ qua. Dùng cách này để cập nhật video mới của kênh.
- Video riêng tư, video đã bị xoá hoặc video dành cho hội viên (khi chưa có cookies) sẽ lỗi và được ghi vào `failed.txt`.
- Nếu đột nhiên tải lỗi hàng loạt, xem phần **Tự động cập nhật** bên dưới.

## Dùng thử và kích hoạt

- Mỗi máy tính được **dùng thử 30 phút**, tính cộng dồn thời gian chương trình đang mở. Tắt rồi mở lại thì tính tiếp, không bắt đầu lại từ đầu. Thanh tiêu đề cửa sổ hiện thời gian còn lại.
- Hết 30 phút, chương trình dừng lượt tải đang chạy (video đã tải xong vẫn được giữ) và hiện hộp thoại kích hoạt.
- **Cách kích hoạt:** bấm **🔑 Kích hoạt** (hoặc đợi hộp thoại hiện ra), bấm **Sao chép** để chép **Mã máy** rồi gửi cho người bán. Nhận lại **mã kích hoạt**, dán vào ô rồi bấm **Kích hoạt**. Sau khi kích hoạt, chương trình dùng không giới hạn trên máy đó.
- Mã kích hoạt chỉ dùng được trên đúng máy có Mã máy đã gửi.
- Dòng lệnh: `run.bat --machine-code` để xem mã máy, `run.bat --activate MÃ-KÍCH-HOẠT` để kích hoạt.

## Tự động cập nhật

YouTube thay đổi thường xuyên, và yt-dlp (thư viện dùng để tải) thường sửa theo trong vài ngày.

- **Mỗi lần mở**, chương trình tự cập nhật yt-dlp lên bản mới nhất trước khi cho tải. Thường mất vài giây. Dòng cuối cửa sổ hiện phiên bản đang dùng. Có thể bấm **⟳ Kiểm tra cập nhật** bất cứ lúc nào.
- **Khi YouTube vừa thay đổi:** nếu 3 video liên tiếp lỗi kiểu "không trích xuất được", chương trình dừng lại và hỏi có muốn chuyển sang **bản thử nghiệm (nightly)** của yt-dlp không. Bản sửa thường có ở đó trước, vài ngày đến vài tuần sau mới vào bản ổn định. Đồng ý thì chương trình tự cập nhật rồi mở lại. Muốn quay về bản ổn định thì bỏ tick ô **Dùng bản thử nghiệm (nightly)**.
- **Cảnh báo:** chương trình báo (chữ đỏ ở dòng cuối và trong log) khi không cập nhật được do mất mạng, hoặc khi **Python trên máy quá cũ** so với yêu cầu của yt-dlp mới. Trường hợp Python cũ, chương trình sẽ kẹt ở bản cũ và dần không tải được nữa. Cách xử lý: cài Python mới rồi chạy lại file cài đặt.
- **Dòng lệnh:** tự cập nhật trước khi tải. `--no-update` để bỏ qua, `--channel nightly` hoặc `--channel stable` để chọn bản (lựa chọn được ghi nhớ). Nếu dừng vì yt-dlp lỗi, chương trình thoát với mã `4`.

Lưu ý: tự động cập nhật chỉ xử lý các **thay đổi kỹ thuật** của YouTube. Thay đổi về **chính sách, điều khoản** là chuyện pháp lý, bạn cần tự theo dõi.

> Chỉ tải nội dung bạn có quyền sử dụng (kênh của bạn, nội dung có giấy phép cho phép...). Tải video từ YouTube có thể vi phạm Điều khoản dịch vụ của YouTube và luật bản quyền.

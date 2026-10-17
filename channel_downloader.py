"""
Download Tool
--------------------------
Nhận link của 1 kênh YouTube và tải toàn bộ video của kênh đó về máy.

  - Chạy giao diện (GUI):   python channel_downloader.py
  - Chạy dòng lệnh (CLI):   python channel_downloader.py <link_kenh> [-o thu_muc] [-q 1080] [--shorts] [--live] [--cc-only]

Dựa trên yt-dlp. Video đã tải được ghi vào file "downloaded.txt" trong thư mục kênh,
nên chạy lại lần sau sẽ chỉ tải video mới / video còn thiếu.

Chỉ dùng để tải nội dung bạn có quyền sử dụng (kênh của bạn, video Creative Commons,
hoặc được chủ kênh cho phép).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

# yt-dlp được import khi cần (load_ytdlp) chứ không import ngay: chương trình cập nhật yt-dlp
# lúc khởi động trước, nhờ vậy dùng được bản mới ngay trong lần mở này.
yt_dlp = None


def load_ytdlp():
    global yt_dlp
    if yt_dlp is None:
        import yt_dlp as module
        yt_dlp = module
    return yt_dlp

import trial as trial_mod

try:
    import imageio_ffmpeg
except ImportError:  # ffmpeg hệ thống vẫn dùng được nếu có trong PATH
    imageio_ffmpeg = None


QUALITIES = {
    "Tốt nhất": None,
    "2160p (4K)": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
    "Chỉ âm thanh (MP3)": "audio",
}

TABS = {"videos": "Videos", "shorts": "Shorts", "streams": "Live"}

RIGHTS_NOTICE = (
    "Video trên YouTube, Bilibili, Dailymotion, TikTok, Douyin… thuộc bản quyền của người tạo ra chúng. "
    "Điều khoản dịch vụ của các trang này thường không cho phép tải video nếu không được chủ sở hữu "
    "cho phép.\n\n"
    "Chỉ tiếp tục nếu bạn có quyền tải nội dung này, ví dụ:\n"
    "  • đây là kênh / video của chính bạn\n"
    "  • video có giấy phép Creative Commons\n"
    "  • chủ sở hữu đã cho phép bạn tải\n\n"
    "Không đăng lại hay dùng cho mục đích thương mại khi chưa được phép."
)
RIGHTS_QUESTION = "Bạn xác nhận mình có quyền tải nội dung này?"


def is_creative_commons(info: dict) -> bool:
    return "creative commons" in (info.get("license") or "").lower()


# Video đang phát / sắp phát: tải lúc này sẽ ghi luồng trực tiếp rất lâu hoặc báo lỗi
LIVE_STATUSES = {
    "is_live": "đang phát trực tiếp",
    "is_upcoming": "sắp phát / chưa công chiếu",
    "post_live": "vừa phát xong, YouTube chưa xử lý xong",
}
UPCOMING_ERRORS = ("this live event will begin", "premieres in", "premiere will begin")
RATE_LIMIT_ERRORS = ("http error 429", "too many requests", "not a bot", "rate-limit", "rate limit",
                     "blocked by server (412)", "rejected by server (352)")  # 412 / 352: Bilibili chống thu thập
DISK_FULL_ERRORS = ("no space left", "errno 28", "winerror 112", "not enough space on the disk")
# Dấu hiệu yt-dlp chưa theo kịp thay đổi của YouTube (cần bản yt-dlp mới hơn)
EXTRACTOR_BROKEN_ERRORS = (
    "unable to extract", "requested format is not available", "signature extraction failed",
    "nsig extraction failed", "challenge solving failed", "only images are available",
    "precondition check failed", "http error 403", "please report this issue",
)
BROKEN_STREAK = 3  # số video lỗi kiểu này liên tiếp thì dừng
# Trang bắt buộc có cookies trình duyệt (Douyin, Ixigua…): video nào cũng sẽ lỗi → dừng và hướng dẫn
NEEDS_COOKIES_ERRORS = ("cookies (not necessarily logged in) are needed", "fresh cookies", "cookies are needed")

GB = 1024 ** 3


def classify_error(message: str) -> str:
    """'rate_limit' | 'needs_cookies' | 'disk_full' | 'upcoming' | 'extractor_broken' | 'other'"""
    m = message.lower()
    if any(p in m for p in RATE_LIMIT_ERRORS):
        return "rate_limit"
    if any(p in m for p in NEEDS_COOKIES_ERRORS):
        return "needs_cookies"
    if any(p in m for p in DISK_FULL_ERRORS):
        return "disk_full"
    if any(p in m for p in UPCOMING_ERRORS):
        return "upcoming"
    if any(p in m for p in EXTRACTOR_BROKEN_ERRORS):
        return "extractor_broken"
    return "other"


def estimate_size(info: dict) -> int:
    """Ước lượng dung lượng (byte) của các định dạng sẽ tải; 0 nếu YouTube không cho biết."""
    formats = info.get("requested_formats") or [info]
    return sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in formats)


def fmt_size(n: float) -> str:
    return f"{n / GB:.1f} GB" if n >= GB else f"{n / 1024 ** 2:.0f} MB"


RATE_LIMIT_MESSAGE = (
    "Trang web đang tạm chặn vì tải quá nhiều (lỗi 429 / yêu cầu xác minh không phải bot).\n"
    "Đã dừng để tránh bị chặn lâu hơn. Hãy đợi vài giờ rồi chạy lại — tool sẽ tải tiếp từ chỗ dừng."
)
BILIBILI_BLOCK_MESSAGE = (
    "Bilibili đang tạm chặn máy này (mã 412 / 352 — cơ chế chống thu thập dữ liệu khi gửi nhiều yêu cầu).\n"
    "Cách khắc phục:\n"
    "  • đợi 15–30 phút rồi chạy lại — tool sẽ tải tiếp từ chỗ dừng\n"
    "  • mở bilibili.com bằng Firefox, rồi chọn “firefox” ở mục Cookies từ trình duyệt (ít bị chặn hơn)\n"
    "  • chọn 1 ở “Số video tải cùng lúc”"
)


class Cancelled(Exception):
    pass


class StopRun(Exception):
    """Dừng cả lượt tải vì lý do không nên thử tiếp (bị YouTube chặn, ổ đĩa đầy)."""


class ExtractorBroken(StopRun):
    """Nhiều video liên tiếp lỗi kiểu "không trích xuất được" → yt-dlp cần bản mới hơn."""


@dataclass
class Options:
    url: str
    output_dir: Path
    quality: int | str | None = None  # None = tốt nhất, int = chiều cao tối đa, "audio" = mp3
    tabs: list[str] = field(default_factory=lambda: ["videos"])
    subtitles: bool = False
    thumbnail: bool = False
    cookies_browser: str | None = None  # "chrome", "edge", "firefox"... cho video giới hạn tuổi / thành viên
    cookies_file: str | None = None  # file cookies.txt (định dạng Netscape) xuất từ trình duyệt bằng tiện ích
    tiktok_whole_channel: bool = False  # link 1 video TikTok → tải cả kênh của tài khoản đăng video đó
    cc_only: bool = False  # chỉ tải video có giấy phép Creative Commons
    workers: int = 2  # số video tải cùng lúc (1–3); đo thực tế: 2 nhanh nhất, 3 không nhanh hơn
    sleep_min: float = 2.0  # mỗi luồng nghỉ ngẫu nhiên giữa các video (giây); 0 = không nghỉ
    sleep_max: float = 5.0
    min_free_gb: float = 2.0  # luôn chừa lại ít nhất bấy nhiêu GB trống trên ổ đĩa


def find_ffmpeg() -> str | None:
    path = shutil.which("ffmpeg")
    if path:
        return path
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def find_js_runtime() -> dict:
    """yt-dlp cần 1 JS runtime (deno / node / bun) để giải mã chữ ký video YouTube."""
    # Bản Node.js riêng do bộ cài tự tải về (khi máy chưa có sẵn)
    private_node = Path(__file__).resolve().parent / "runtime" / "node" / "node.exe"
    if private_node.is_file():
        return {"node": {"path": str(private_node)}}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            return {name: {"path": path}}
    # Vừa cài Node/Deno mà PATH của tiến trình này chưa cập nhật → tìm ở nơi cài mặc định
    env = os.environ
    for name, path in (
        ("node", Path(env.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"),
        ("node", Path(env.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe"),
        ("deno", Path.home() / ".deno" / "bin" / "deno.exe"),
    ):
        if path.is_file():
            return {name: {"path": str(path)}}
    return {}


def normalize_channel_url(url: str) -> str:
    """Đưa link kênh về dạng gốc (bỏ /videos, /shorts, /featured, query...)."""
    url = url.strip()
    if not url:
        raise ValueError("Chưa nhập link kênh.")
    if not re.match(r"^https?://", url):
        if url.startswith("@"):
            url = "https://www.youtube.com/" + url
        else:
            url = "https://" + url
    url = url.split("?")[0].split("#")[0].rstrip("/")
    m = re.match(
        r"^(https?://(?:www\.|m\.)?youtube\.com/(?:@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+))",
        url,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            "Link không giống link kênh YouTube.\n"
            "Ví dụ hợp lệ: https://www.youtube.com/@tenkenh  hoặc  https://www.youtube.com/channel/UC..."
        )
    return re.sub(r"://(?:m\.|www\.)?youtube\.com", "://www.youtube.com", m.group(1), flags=re.IGNORECASE)


# ---------------------------------------------------------------- các trang khác ngoài YouTube

# Tên hiển thị theo tên miền (dùng cho log và tên thư mục lưu)
SITE_NAMES = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "bilibili.com": "Bilibili", "b23.tv": "Bilibili",
    "dailymotion.com": "Dailymotion", "dai.ly": "Dailymotion", "douyin.com": "Douyin", "ixigua.com": "Ixigua",
    "tiktok.com": "TikTok", "toutiao.com": "Toutiao", "weibo.com": "Weibo", "weibo.cn": "Weibo",
    "youku.com": "Youku", "iqiyi.com": "iQiyi", "acfun.cn": "AcFun", "vimeo.com": "Vimeo",
    "facebook.com": "Facebook", "instagram.com": "Instagram", "twitter.com": "X", "x.com": "X",
}
# Trang thư viện yt-dlp không hỗ trợ → báo ngay thay vì thử rồi lỗi
UNSUPPORTED_SITES = {"kuaishou.com": "Kuaishou", "kwai.com": "Kwai", "gifshow.com": "Kuaishou"}
# Trang bắt buộc cookies trình duyệt (không cần đăng nhập)
COOKIE_SITES = {"Douyin", "Ixigua", "Toutiao"}
COOKIE_FORMAT_MESSAGE = ("File cookies không đúng định dạng. Hãy xuất lại bằng tiện ích “Get cookies.txt LOCALLY” "
                         "(chọn định dạng Netscape) khi đang mở trang cần tải.")
# Link 1 video TikTok (kể cả link rút gọn vm./vt.tiktok.com)
TIKTOK_VIDEO_RE = re.compile(r"/video/\d+|//(?:vm|vt)\.tiktok\.com/|tiktok\.com/t/", re.IGNORECASE)


@dataclass
class Target:
    kind: str  # "youtube_channel" (tải theo tab Videos/Shorts/Live) | "other" (kênh / playlist / video bất kỳ)
    url: str
    site: str  # tên trang để hiển thị


def site_name(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    for domain, name in SITE_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return re.sub(r"^(www|m)\.", "", host) or "web"


def has_extractor(url: str) -> bool:
    """yt-dlp có bộ đọc riêng cho link này không (không tính bộ đọc 'chung' Generic)."""
    load_ytdlp()
    from yt_dlp.extractor import gen_extractor_classes
    return any(ie.ie_key() != "Generic" and ie.suitable(url) for ie in gen_extractor_classes())


def resolve_target(url: str) -> Target:
    """Nhận diện link người dùng dán vào. Báo lỗi (ValueError) nếu link hỏng / trang không hỗ trợ."""
    url = url.strip()
    if not url:
        raise ValueError("Chưa nhập link.")
    if url.startswith("@"):
        url = "https://www.youtube.com/" + url
    elif not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    try:
        return Target("youtube_channel", normalize_channel_url(url), "YouTube")
    except ValueError:
        pass
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if "." not in host:
        raise ValueError("Link không hợp lệ.\nVí dụ: https://www.bilibili.com/video/BV…  hoặc  "
                         "https://www.youtube.com/@tenkenh")
    for domain, name in UNSUPPORTED_SITES.items():
        if host == domain or host.endswith("." + domain):
            raise ValueError(f"{name} hiện chưa được hỗ trợ.")
    return Target("other", url, site_name(url))


def explain_error(message: str, site: str) -> str:
    """Đổi lỗi kỹ thuật của yt-dlp thành hướng dẫn dễ hiểu."""
    m = message.lower()
    kind = classify_error(message)
    if kind == "rate_limit":
        return BILIBILI_BLOCK_MESSAGE if site == "Bilibili" else RATE_LIMIT_MESSAGE
    if kind == "needs_cookies":
        return (f"{site} yêu cầu cookies trình duyệt (không cần đăng nhập). Chọn 1 trong 2 cách:\n"
                f"  • mở trang {site} bằng Firefox ít nhất 1 lần, rồi chọn “firefox” ở mục Cookies\n"
                f"  • hoặc mở {site} bằng trình duyệt bất kỳ, xuất cookies bằng tiện ích “Get cookies.txt LOCALLY”, "
                "rồi chọn “file cookies.txt…” ở mục Cookies\n"
                "(Chọn trực tiếp Chrome / Edge thường không được vì Windows khoá cookies của chúng.)")
    if "netscape format" in m or "cookies file" in m:
        return COOKIE_FORMAT_MESSAGE
    if "impersonat" in m:
        return ("Phần mềm thiếu thành phần cần cho trang này. Hãy bấm “⟳ Kiểm tra cập nhật” rồi mở lại "
                "chương trình (hoặc chạy lại file cài đặt).")
    if "unsupported url" in m:
        return f"Link này không được hỗ trợ ({site}). Hãy thử link của từng video."
    if "secondary user id" in m:
        return ("Không đọc được danh sách video từ trang tài khoản TikTok.\n"
                "Thử cách khác: dán link 1 video bất kỳ của tài khoản này và tick ô "
                "“TikTok: tải cả kênh từ link 1 video”.")
    first = message.strip().splitlines()[0] if message.strip() else message
    return clean_library_message(first)


# Phần đuôi kỹ thuật trong thông báo gốc của thư viện tải video (link báo lỗi, lệnh cập nhật, tên thư viện…)
_LIBRARY_NOISE = [
    re.compile(r"\s*Also see\b.*", re.IGNORECASE | re.DOTALL),
    re.compile(r";?\s*please report this issue.*", re.IGNORECASE | re.DOTALL),
    re.compile(r"\s*Confirm you are on the latest version.*", re.IGNORECASE | re.DOTALL),
    re.compile(r"\s*Use --cookies-from-browser or --cookies[^.]*\.?", re.IGNORECASE),
    re.compile(r"\s*See\s+https?://\S+\s+for\b[^.]*\.?", re.IGNORECASE),
    re.compile(r"\s*https?://(?:github\.com|pypi\.org)/\S*yt-dlp\S*", re.IGNORECASE),
]


def clean_library_message(message: str) -> str:
    """Bỏ tên thư viện và hướng dẫn dành cho lập trình viên khỏi thông báo trước khi hiện cho khách."""
    for pattern in _LIBRARY_NOISE:
        message = pattern.sub("", message)
    message = re.sub(r"\byt[-_]dlp\b", "trình tải", message, flags=re.IGNORECASE)
    message = re.sub(r"^\s*(ERROR|WARNING):\s*", "", message.strip())
    return message.strip() or "Lỗi không xác định."


def default_output_dir() -> Path:
    """Mặc định lưu vào Downloads; nếu ổ đó còn ít chỗ (< 20 GB) thì chọn ổ còn trống nhiều nhất."""
    home = Path.home() / "Downloads" / "YouTube"
    try:
        if shutil.disk_usage(Path.home()).free >= 20 * GB or sys.platform != "win32":
            return home
        best, best_free = home, shutil.disk_usage(Path.home()).free
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            try:
                free = shutil.disk_usage(root).free
            except OSError:  # ổ không tồn tại / ổ CD trống
                continue
            if free > best_free:
                best, best_free = root / "YouTube", free
        return best
    except OSError:
        return home


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "channel"


def title_budget(folder: Path) -> int:
    """Số byte tối đa cho tiêu đề trong tên file để đường dẫn không vượt giới hạn 260 ký tự của Windows."""
    # "2024-05-01 - " + " [xxxxxxxxxxx].f999.mp4.part.ytdl" + dấu "\"
    overhead = len("2024-05-01 - ") + len(" [xxxxxxxxxxx].f999.mp4.part.ytdl") + 1
    return max(20, min(150, 250 - len(str(folder.resolve())) - overhead))


def format_sort(quality) -> list[str]:
    """Ưu tiên độ phân giải, sau đó ưu tiên H.264 + m4a để file ghép ra là .mp4 (dễ xem trên mọi máy).
    Độ phân giải cao (vd. 4K) chỉ có VP9/AV1 thì vẫn lấy độ phân giải cao, file ra là .mkv."""
    if quality == "audio":
        return []
    res = "res" if quality is None else f"res:{quality}"
    return [res, "vcodec:h264", "ext:mp4:m4a"]


# ====================================================================== cập nhật yt-dlp
# YouTube thay đổi thường xuyên; yt-dlp sửa theo trong vài ngày. Mỗi lần mở, chương trình tự
# cập nhật yt-dlp. Nếu bản ổn định chưa kịp sửa, có thể chuyển sang bản thử nghiệm (nightly).

STATE_FILE = Path(__file__).resolve().parent / "update_state.json"
CHANNELS = {"stable": "ổn định", "nightly": "thử nghiệm (nightly)"}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(**changes) -> dict:
    state = load_state() | changes
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return state


# ====================================================================== điều khoản sử dụng (EULA)
# Lần đầu dùng phải đồng ý EULA.md. Phiên bản đã đồng ý được lưu trong update_state.json;
# người bán tăng "Phiên bản:" trong EULA.md thì khách được hỏi lại.

EULA_FILE = Path(__file__).resolve().parent / "EULA.md"
EULA_QUESTION = "Bạn đã đọc và đồng ý với Điều khoản sử dụng?"


def load_eula() -> tuple[str, str]:
    """(phiên bản, nội dung để hiện cho khách) của EULA.md; ("", "") nếu không đọc được file.
    Bỏ ghi chú bản nháp dành cho người bán và các ký hiệu Markdown."""
    try:
        text = EULA_FILE.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    text = re.sub(r"<!-- BẢN NHÁP.*?<!-- /BẢN NHÁP -->\s*", "", text, flags=re.S)
    m = re.search(r"^Phiên bản:\s*(\S+)", text, re.M)
    version = m.group(1) if m else "sha-" + hashlib.sha256(text.encode()).hexdigest()[:12]
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"^(\s*)- ", r"\1• ", text, flags=re.M)
    text = text.replace("**", "").replace("`", "")
    return version, text.strip()


def eula_accepted(version: str) -> bool:
    return load_state().get("eula_version") == version


def accept_eula(version: str) -> None:
    save_state(eula_version=version, eula_accepted_at=datetime.now().isoformat(timespec="seconds"))


def get_channel() -> str:
    channel = load_state().get("channel")
    return channel if channel in CHANNELS else "stable"


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def installed_ytdlp_version() -> str | None:
    """Đọc phiên bản yt-dlp đang cài bằng tiến trình riêng (đúng cả khi vừa cập nhật xong)."""
    try:
        r = subprocess.run(
            [sys.executable, "-c", "from importlib.metadata import version; print(version('yt-dlp'))"],
            capture_output=True, text=True, timeout=30, **_no_window())
        return r.stdout.strip() or None
    except Exception:
        return None


def version_date(version: str | None) -> date | None:
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", version or "")
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError:
        return None


def pypi_latest() -> tuple[str | None, str | None]:
    """(bản ổn định mới nhất, yêu cầu Python) của yt-dlp trên PyPI; (None, None) nếu không kết nối được."""
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=10) as r:
            info = json.load(r)["info"]
        return info.get("version"), info.get("requires_python")
    except Exception:
        return None, None


def python_supports(requires: str | None) -> bool:
    m = re.search(r">=\s*(\d+)\.(\d+)", requires or "")
    return not m or sys.version_info[:2] >= (int(m[1]), int(m[2]))


@dataclass
class UpdateResult:
    channel: str
    before: str | None
    after: str | None
    ok: bool
    error: str = ""
    warning: str = ""  # vấn đề người dùng cần xử lý (Python quá cũ, không cập nhật được...)
    python_too_old: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.before and self.after and self.before != self.after)

    def summary(self) -> str:
        """Câu hiển thị cho khách: không nêu tên / phiên bản thư viện (chi tiết lưu trong update_state.json)."""
        if self.changed:
            return "Đã cập nhật lên bản mới nhất — sẵn sàng sử dụng."
        if self.python_too_old:
            return "Có bản cập nhật mới nhưng cần cài lại phần mềm."
        if self.ok:
            return "Tất cả thư viện đã là bản mới nhất — sẵn sàng sử dụng."
        return "Chưa kiểm tra được cập nhật — vẫn dùng được bản hiện tại."


# Thư viện phụ yt-dlp gợi ý nhưng phần mềm KHÔNG cài:
#   mutagen — giấy phép GPL-2.0+, chỉ dùng để nhúng ảnh bìa vào file (tính năng này không bật).
#   Là thư viện Python chạy chung tiến trình nên dễ kéo cả phần mềm vào ràng buộc GPL → loại bỏ.
EXCLUDED_DEPS = {"mutagen"}

# Chạy bằng Python của môi trường cài đặt: đọc danh sách thư viện phụ (đúng phiên bản yt-dlp yêu cầu)
# của các nhóm "default" và "curl-cffi", bỏ những thư viện trong EXCLUDED_DEPS
_EXTRAS_SCRIPT = r"""
import json, sys
from importlib.metadata import requires
from pip._vendor.packaging.requirements import Requirement
excluded = set(json.loads(sys.argv[1]))
specs = []
for line in requires("yt-dlp") or []:
    req = Requirement(line)
    if req.name.lower() in excluded or req.marker is None:
        continue
    if any(req.marker.evaluate({"extra": e}) for e in ("default", "curl-cffi")):
        extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        specs.append(f"{req.name}{extras}{req.specifier}")
print(json.dumps(specs))
"""


def sync_ytdlp_extras() -> tuple[bool, str]:
    """Cài các thư viện phụ yt-dlp cần (curl-cffi cho Dailymotion, yt-dlp-ejs giải mã YouTube…),
    trừ EXCLUDED_DEPS; gỡ mutagen nếu bản cũ đã lỡ cài. Trả về (thành công, lỗi)."""
    try:
        r = subprocess.run([sys.executable, "-c", _EXTRAS_SCRIPT, json.dumps(sorted(EXCLUDED_DEPS))],
                           capture_output=True, text=True, timeout=60, **_no_window())
        specs = json.loads(r.stdout.strip() or "[]")
        if r.returncode != 0 or not specs:
            return False, (r.stderr.strip().splitlines() or ["không đọc được danh sách thư viện phụ"])[-1]
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
                            "--timeout", "15", "--retries", "1", *specs],
                           capture_output=True, text=True, timeout=300, **_no_window())
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", *sorted(EXCLUDED_DEPS)],
                       capture_output=True, text=True, timeout=120, **_no_window())
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    except Exception as e:
        return False, str(e)


def update_ytdlp(channel: str | None = None) -> UpdateResult:
    """Cập nhật yt-dlp (kèm thành phần giải mã yt-dlp-ejs) lên bản mới nhất của kênh đã chọn."""
    channel = channel or get_channel()
    before = installed_ytdlp_version()
    latest, requires = pypi_latest()

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "-q",
           "--timeout", "15", "--retries", "1"]
    spec = "yt-dlp"  # thư viện phụ được cài riêng ở sync_ytdlp_extras (để bỏ được mutagen)
    if channel == "nightly":
        cmd.append("--pre")
    elif before and "dev" in before and latest:
        # Từ nightly quay về bản ổn định: pip không tự hạ phiên bản nên phải chỉ rõ
        spec = f"yt-dlp=={latest}"
    try:
        r = subprocess.run(cmd + [spec], capture_output=True, text=True, timeout=300, **_no_window())
        if r.returncode == 0:
            extras_ok, extras_error = sync_ytdlp_extras()
            if not extras_ok:
                r = subprocess.CompletedProcess(r.args, 1, "", extras_error)
        error = (r.stderr or r.stdout).strip()
        # Mất mạng mà bản cũ vẫn "thoả yêu cầu" thì pip vẫn trả mã 0 → phải đọc cảnh báo kết nối
        offline = re.search(r"could not fetch url|failed to establish|connection|retrying|"
                            r"no matching distribution|getaddrinfo", error, re.IGNORECASE)
        ok = r.returncode == 0 and not offline
        if offline and r.returncode == 0:
            error = "không kết nối được máy chủ cập nhật"
    except subprocess.TimeoutExpired:
        ok, error = False, "quá thời gian chờ"
    except Exception as e:
        ok, error = False, str(e)

    after = installed_ytdlp_version()
    result = UpdateResult(channel, before, after, ok, "" if ok else error.splitlines()[-1] if error else "")
    if latest and requires and not python_supports(requires):
        # pip lặng lẽ giữ bản cũ khi bản mới không hỗ trợ Python trên máy → phải tự kiểm tra
        result.python_too_old = True
        result.warning = (
            "Đã có bản cập nhật mới nhưng máy này cần cài lại phần mềm mới nhận được. Nếu không cập nhật, "
            "phần mềm sẽ dần không tải được nữa. Hãy liên hệ người bán để nhận file cài đặt mới nhất.")
    elif not ok:
        released = version_date(after)
        age = (date.today() - released).days if released else None
        result.warning = (
            "Chưa kiểm tra được cập nhật. Hãy kiểm tra kết nối Internet rồi bấm “⟳ Kiểm tra cập nhật”."
            + (f" Bản đang dùng đã {age} ngày chưa được cập nhật." if age is not None and age > 30 else ""))
    # Chi tiết kỹ thuật (tên / phiên bản thư viện, lỗi) chỉ lưu lại để hỗ trợ khách, không hiển thị
    save_state(channel=channel, last_check=datetime.now().isoformat(timespec="seconds"),
               last_version=after, last_ok=ok, last_error=result.error,
               python_too_old=result.python_too_old)
    return result


def restart_program():
    """Mở lại chương trình (để dùng bản yt-dlp vừa cập nhật khi bản cũ đã được nạp)."""
    subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=str(Path(__file__).resolve().parent))


class ChannelDownloader:
    """
    Callbacks (đều tuỳ chọn):
      log(msg)                         -- dòng log
      overall(done, total, title)      -- tiến độ tổng (số video)
      progress(percent, speed, eta)    -- tiến độ video hiện tại
    """

    def __init__(self, opts: Options, log: Callable[[str], None] = print,
                 overall: Callable[[int, int, str], None] | None = None,
                 progress: Callable[[float, str, str], None] | None = None):
        load_ytdlp()
        self.opts = opts
        self.log = log
        self.overall = overall or (lambda d, t, title: None)
        self.progress = progress or (lambda p, s, e: None)
        self._cancel = threading.Event()  # người dùng bấm Dừng
        self._halt = threading.Event()    # 1 luồng gặp lý do phải dừng → các luồng khác không lấy video mới
        self._lock = threading.Lock()
        self._active: dict[int, tuple[float, float, float]] = {}  # luồng → (%, byte/s, giây còn lại)
        self._inflight: dict[int, int] = {}  # luồng → dung lượng đang giữ chỗ trên ổ đĩa
        self._temp_files: list[str] = []  # bản sao tạm của file cookies, xoá khi chạy xong

    def cancel(self):
        self._cancel.set()

    def _pause(self):
        """Nghỉ ngẫu nhiên giữa 2 video để không gửi yêu cầu dồn dập (giảm nguy cơ bị chặn).
        Dùng Event.wait nên bấm Dừng vẫn có tác dụng ngay."""
        if self.opts.sleep_max <= 0:
            return
        seconds = random.uniform(self.opts.sleep_min, max(self.opts.sleep_min, self.opts.sleep_max))
        if self._cancel.wait(seconds):
            raise Cancelled()

    def _check_disk(self, folder: Path, need: int = 0, worker: int | None = None):
        """Dừng nếu ổ đĩa không đủ chỗ. Khi ghép video + âm thanh, file tạm và file ghép
        tồn tại cùng lúc nên cần khoảng gấp đôi dung lượng video. Các video đang tải ở luồng
        khác cũng được tính vào (chúng sẽ còn ghi thêm)."""
        free = shutil.disk_usage(folder).free
        reserve = int(self.opts.min_free_gb * GB)
        with self._lock:
            others = sum(v for w, v in self._inflight.items() if w != worker)
            enough = free >= need * 2 + others + reserve
            if enough and worker is not None and need:
                self._inflight[worker] = need * 2  # giữ chỗ cho video này tới khi tải xong
        if not enough:
            raise StopRun(
                f"Ổ đĩa sắp đầy: còn trống {fmt_size(free)}"
                + (f", video tiếp theo cần khoảng {fmt_size(need * 2)} (tính cả file tạm)" if need else "")
                + (f", các video đang tải dở cần thêm {fmt_size(others)}" if others else "")
                + f", và tool luôn chừa lại {fmt_size(reserve)}.\n"
                "Hãy giải phóng dung lượng hoặc chọn thư mục lưu ở ổ khác, rồi chạy lại — "
                "tool sẽ tải tiếp từ chỗ dừng."
            )

    # ---------- yt-dlp plumbing ----------

    class _Logger:
        def __init__(self, outer: "ChannelDownloader", mute_errors: bool = False):
            self.outer = outer
            self.mute_errors = mute_errors  # lỗi được xử lý & log ở nơi gọi

        def debug(self, msg):
            if msg.startswith("[download] Destination") or msg.startswith("[Merger]") \
                    or msg.startswith("[ExtractAudio]"):
                self.outer.log("   " + msg)

        def info(self, msg):
            pass

        def warning(self, msg):
            self.outer.log("   ⚠ " + clean_library_message(msg))

        def error(self, msg):
            if not self.mute_errors:
                self.outer.log("   ✖ " + clean_library_message(msg))

    def _base_params(self) -> dict:
        params = {
            "logger": self._Logger(self),
            "quiet": True,
            "no_warnings": False,
            "ignoreerrors": False,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
        }
        js = find_js_runtime()
        if js:
            params["js_runtimes"] = js
        if self.opts.cookies_browser:
            params["cookiesfrombrowser"] = (self.opts.cookies_browser,)
        if self.opts.cookies_file:
            params["cookiefile"] = self._cookie_copy()
        return params

    def _cookie_copy(self) -> str:
        """yt-dlp ghi đè file cookies khi đóng → mỗi YoutubeDL dùng 1 bản sao tạm riêng: không sửa file của
        người dùng, và các luồng tải không ghi đè lên nhau. Bản sao được xoá khi chạy xong."""
        fd, path = tempfile.mkstemp(prefix="DownloadTool-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(self.opts.cookies_file, path)
        self._temp_files.append(path)
        return path

    def _make_hook(self, worker: int):
        def hook(d):
            if self._cancel.is_set():
                raise Cancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                self._report(worker, (done / total * 100) if total else 0.0, d.get("speed") or 0, d.get("eta") or 0)
            elif d.get("status") == "finished":
                self._report(worker, 100.0, 0, 0)
        return hook

    def _report(self, worker: int, pct: float | None, speed: float = 0, eta: float = 0):
        """Gộp tiến độ của các luồng: % trung bình, tổng tốc độ, thời gian còn lại lâu nhất.
        pct=None: luồng này đang không tải (nghỉ / lấy thông tin)."""
        with self._lock:
            if pct is None:
                self._active.pop(worker, None)
            else:
                self._active[worker] = (pct, speed, eta)
            active = list(self._active.values())
        if not active:
            return self.progress(0, "", "")
        pct_avg = sum(a[0] for a in active) / len(active)
        speed_sum = sum(a[1] for a in active)
        eta_max = int(max(a[2] for a in active))
        speed_text = f"{speed_sum / 1024 ** 2:.1f} MB/s" if speed_sum else ""
        if len(active) > 1 and speed_text:
            speed_text += f" · {len(active)} video"
        self.progress(pct_avg, speed_text, f"{eta_max // 60:02d}:{eta_max % 60:02d}" if speed_sum else "")

    # ---------- steps ----------

    def list_videos(self, channel_url: str) -> tuple[str, list[tuple[str, str, str, str | None]]]:
        """Trả về (tên kênh, [(tab, video_id, title, live_status), ...])."""
        params = self._base_params() | {"extract_flat": "in_playlist", "skip_download": True,
                                        "logger": self._Logger(self, mute_errors=True)}
        channel_name = None
        entries: list[tuple[str, str, str, str | None]] = []
        with yt_dlp.YoutubeDL(params) as ydl:
            for tab in self.opts.tabs:
                if self._cancel.is_set():
                    raise Cancelled()
                self.log(f"🔎 Đang lấy danh sách {TABS[tab]} ...")
                try:
                    info = ydl.extract_info(f"{channel_url}/{tab}", download=False)
                except yt_dlp.utils.DownloadError as e:
                    # Kênh không có tab này (vd. không có Shorts/Live)
                    reason = str(e).splitlines()[0].split(": ")[-1]
                    self.log(f"   (bỏ qua {TABS[tab]}: {reason})")
                    continue
                channel_name = channel_name or info.get("channel") or info.get("uploader") or info.get("title")
                count = 0
                for e in info.get("entries") or []:
                    if e and e.get("id"):
                        entries.append((tab, e["id"], e.get("title") or e["id"], e.get("live_status")))
                        count += 1
                self.log(f"   → {count} {TABS[tab]}")
        return channel_name or "channel", entries

    def list_generic(self, target: Target) -> tuple[str, list[tuple]]:
        """Link không phải kênh YouTube (Bilibili, Dailymotion, TikTok, Douyin…): kênh, playlist hoặc 1 video.
        Trả về (tên, [(tab, video_id, title, live_status, url, ie_key), ...])."""
        params = self._base_params() | {"extract_flat": "in_playlist", "skip_download": True,
                                        "logger": self._Logger(self, mute_errors=True)}
        self.log(f"🔎 Đang đọc link {target.site} ...")
        if not has_extractor(target.url):
            self.log(f"   ⚠ {target.site} không có trong danh sách trang được hỗ trợ — đang thử cách đọc chung, "
                     "có thể không tải được.")
        url, via_video, owner = target.url, False, None
        with yt_dlp.YoutubeDL(params) as ydl:
            try:
                if target.site == "TikTok" and self.opts.tiktok_whole_channel and TIKTOK_VIDEO_RE.search(url):
                    # Trang tài khoản TikTok hay không đọc được → lấy mã tài khoản từ 1 video của tài khoản đó
                    video = ydl.extract_info(url, download=False)
                    if not video.get("channel_id"):
                        raise StopRun("Không lấy được mã tài khoản TikTok từ video này.")
                    owner = video.get("uploader") or video.get("channel") or video["channel_id"]
                    self.log(f"   → tải cả kênh của tài khoản “{owner}”")
                    url, via_video = f"tiktokuser:{video['channel_id']}", True
                info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as e:
                if via_video and "secondary user id" in str(e).lower():
                    raise StopRun("TikTok không cho đọc danh sách video của tài khoản này (đã thử cả cách lấy mã "
                                  "tài khoản từ video). Hãy dán link từng video — bỏ tick ô “tải cả kênh”.")
                raise StopRun(explain_error(str(e), target.site))
        # Một số trang (vd. Dailymotion) chỉ trả về mã tài khoản → dùng mã đó làm tên
        name = (owner or info.get("channel") or info.get("uploader") or info.get("playlist_title")
                or info.get("title") or info.get("id") or target.site)
        entries = []
        if info.get("_type") == "playlist":
            for e in info.get("entries") or []:
                if e and e.get("id"):
                    entries.append(("videos", e["id"], e.get("title") or e["id"], e.get("live_status"),
                                    e.get("webpage_url") or e.get("url"), e.get("ie_key") or e.get("extractor_key")))
            self.log(f"   → {len(entries)} video")
        else:
            entries.append(("videos", info["id"], info.get("title") or info["id"], info.get("live_status"),
                            info.get("webpage_url") or target.url, info.get("extractor_key")))
            self.log("   → 1 video")
        return name, entries

    @staticmethod
    def _as_entry(entry: tuple) -> tuple:
        """Chuẩn hoá về (tab, video_id, title, live_status, url, ie_key); mục YouTube cũ chỉ có 4 phần tử."""
        if len(entry) == 6:
            return entry
        tab, vid, title, live_status = entry
        return tab, vid, title, live_status, f"https://www.youtube.com/watch?v={vid}", "Youtube"

    def run(self) -> tuple[int, int, int]:
        """Tải toàn bộ. Trả về (thành công, bỏ qua vì đã có, lỗi)."""
        if self.opts.cookies_file:
            if not Path(self.opts.cookies_file).is_file():
                raise StopRun(f"Không tìm thấy file cookies: {self.opts.cookies_file}")
            # Kiểm tra trước: file sai định dạng mà để yt-dlp tự phát hiện thì lỗi lặp lại cả lúc đóng
            try:
                from yt_dlp.cookies import YoutubeDLCookieJar
                YoutubeDLCookieJar(self.opts.cookies_file).load(ignore_discard=True, ignore_expires=True)
            except Exception:
                raise StopRun(COOKIE_FORMAT_MESSAGE)
        try:
            return self._run()
        finally:
            for path in self._temp_files:  # bản sao tạm của file cookies
                with contextlib.suppress(OSError):
                    os.remove(path)

    def _run(self) -> tuple[int, int, int]:
        target = resolve_target(self.opts.url)
        self.log(f"📺 {target.site}: {target.url}")

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.log("⚠ Thiếu thành phần ghép hình và tiếng — chỉ tải được định dạng có sẵn tiếng (thường tối đa "
                     "720p). Hãy chạy lại file cài đặt để sửa.")

        if target.kind == "youtube_channel":
            channel_name, entries = self.list_videos(target.url)
        else:
            channel_name, entries = self.list_generic(target)
        entries = [self._as_entry(e) for e in entries]
        total = len(entries)
        if total == 0:
            self.log("Không tìm thấy video nào.")
            return 0, 0, 0
        self.log(f"✅ “{channel_name}”: tổng {total} video cần xử lý.\n")

        # Kênh YouTube giữ nguyên tên thư mục cũ (để downloaded.txt cũ vẫn dùng được); trang khác có tên trang phía trước
        folder = channel_name if target.kind == "youtube_channel" else f"{target.site} - {channel_name}"
        channel_dir = self.opts.output_dir / safe_name(folder)
        channel_dir.mkdir(parents=True, exist_ok=True)
        archive = channel_dir / "downloaded.txt"

        params = self._base_params() | {
            "format": ("bestaudio/best" if self.opts.quality == "audio" else
                       "bestvideo*+bestaudio/best" if ffmpeg else "best"),
            "format_sort": format_sort(self.opts.quality),
            "download_archive": str(archive),
            "windowsfilenames": True,
            "continuedl": True,
            "writesubtitles": self.opts.subtitles,
            "writeautomaticsub": False,
            "subtitleslangs": ["vi", "en", "-live_chat"],
            "writethumbnail": self.opts.thumbnail,
            "postprocessors": [],
        }
        if ffmpeg:
            params["ffmpeg_location"] = ffmpeg
            if self.opts.quality == "audio":
                params["postprocessors"].append(
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"})
            else:
                params["merge_output_format"] = "mp4/mkv"  # mkv khi không ghép được vào mp4 (vd. VP9 4K)
            if self.opts.thumbnail:
                params["postprocessors"].append({"key": "EmbedThumbnail"})

        c = {"ok": 0, "skipped": 0, "failed": 0, "not_cc": 0, "live": 0, "done": 0, "broken": 0}
        failures: list[str] = []
        attribution = channel_dir / "ATTRIBUTION.txt"

        # Lọc trước video đã tải / đang phát (không cần hỏi YouTube), phần còn lại đưa vào hàng đợi
        todo: queue.Queue = queue.Queue()
        with yt_dlp.YoutubeDL(params) as probe:
            for idx, (tab, vid, title, live_status, url, ie_key) in enumerate(entries, 1):
                if probe.in_download_archive({"id": vid, "extractor_key": ie_key, "url": url}):
                    c["skipped"] += 1
                elif live_status in LIVE_STATUSES:
                    c["live"] += 1
                    self.log(f"[{idx}/{total}] ⏭ Bỏ qua ({LIVE_STATUSES[live_status]}): {title}")
                else:
                    todo.put((idx, tab, vid, title, url))
        c["done"] = c["skipped"] + c["live"]
        workers = max(1, min(self.opts.workers, todo.qsize()))

        self.log(f"💾 Ổ đĩa còn trống: {fmt_size(shutil.disk_usage(channel_dir).free)}"
                 f" (luôn chừa lại {self.opts.min_free_gb:g} GB)")
        if c["skipped"]:
            self.log(f"⏭ {c['skipped']} video đã tải từ trước — bỏ qua.")
        if todo.qsize():
            self.log(f"⚡ Tải {todo.qsize()} video, {workers} video cùng lúc.")
        if self.opts.sleep_max > 0:
            self.log(f"⏱ Nghỉ ngẫu nhiên {self.opts.sleep_min:g}–{self.opts.sleep_max:g} giây giữa các video.")
        if self.opts.cc_only:
            self.log("🔒 Chế độ Creative Commons: chỉ tải video có giấy phép CC, bỏ qua các video khác.")
            if target.site != "YouTube":
                self.log(f"   ⚠ {target.site} thường không ghi giấy phép của video → ở chế độ này có thể "
                         "không video nào được tải.")
        if target.site in COOKIE_SITES and not (self.opts.cookies_browser or self.opts.cookies_file):
            self.log(f"⚠ {target.site} thường yêu cầu cookies trình duyệt — nếu lỗi, hãy chọn “firefox” hoặc "
                     "“file cookies.txt…” ở mục Cookies.")
        self.log("")
        self.overall(c["done"], total, "")

        def tab_params(tab: str, worker: int) -> dict:
            # Mỗi loại (Videos / Shorts / Live) lưu vào 1 thư mục con riêng
            tab_dir = channel_dir / TABS[tab]
            extra = {"cookiefile": self._cookie_copy()} if self.opts.cookies_file else {}  # bản sao riêng mỗi luồng
            return params | extra | {
                "paths": {"home": str(tab_dir)},
                # Trang không có ngày đăng → lấy theo timestamp, không có nữa thì "NA"
                "outtmpl": {"default": "%(upload_date>%Y-%m-%d,timestamp>%Y-%m-%d|NA)s - "
                                       f"%(title).{title_budget(tab_dir)}B [%(id)s].%(ext)s"},
                "progress_hooks": [self._make_hook(worker)],
            }

        stop: list[BaseException] = []  # lý do dừng đầu tiên (StopRun) hoặc lỗi không lường trước

        def worker_loop(worker: int):
            ydls: dict[str, object] = {}  # mỗi luồng 1 YoutubeDL riêng cho mỗi loại video
            first = True
            try:
                while not self._halt.is_set():
                    if self._cancel.is_set():
                        raise Cancelled()
                    try:
                        idx, tab, vid, title, url = todo.get_nowait()
                    except queue.Empty:
                        return
                    if not first:
                        self._pause()
                    first = False
                    if self._halt.is_set():
                        return
                    if tab not in ydls:
                        ydls[tab] = yt_dlp.YoutubeDL(tab_params(tab, worker))
                    try:
                        self._process_one(ydls[tab], worker, idx, total, vid, title, url, target.site,
                                          channel_dir, attribution, c, failures)
                    finally:
                        self._report(worker, None)
                        with self._lock:
                            self._inflight.pop(worker, None)
                            c["done"] += 1
                            done = c["done"]
                        self.overall(done, total, title)
            except Cancelled:
                self._halt.set()
            except BaseException as e:  # StopRun hoặc lỗi bất ngờ: dừng mọi luồng
                with self._lock:
                    stop.append(e)
                self._halt.set()
            finally:
                for ydl in ydls.values():
                    ydl.close()

        threads = [threading.Thread(target=worker_loop, args=(w,), daemon=True) for w in range(workers)]
        for t in threads:
            t.start()
        try:
            while any(t.is_alive() for t in threads):
                for t in threads:
                    t.join(0.2)  # join có hạn để Ctrl+C (dòng lệnh) vẫn có tác dụng
        except KeyboardInterrupt:
            self.cancel()
            for t in threads:
                t.join()
            raise
        self.progress(0, "", "")

        stop_exc = next((e for e in stop if isinstance(e, StopRun)), None)
        if self._cancel.is_set() and not stop_exc:
            raise Cancelled()
        unexpected = next((e for e in stop if not isinstance(e, StopRun)), None)
        if unexpected:
            raise unexpected
        if not stop_exc:
            self.overall(total, total, "")
        stop_reason = str(stop_exc) if stop_exc else None

        ok, skipped, failed, live = c["ok"], c["skipped"], c["failed"], c["live"]
        head = "⛔ Đã dừng giữa chừng." if stop_reason else "🎉 Xong!"
        summary = f"\n{head} Tải mới: {ok} · Đã có từ trước: {skipped} · Lỗi: {failed}"
        if live:
            summary += f" · Bỏ qua vì đang/sắp phát trực tiếp: {live}"
        if self.opts.cc_only:
            summary += f" · Bỏ qua vì không phải CC: {c['not_cc']}"
        self.log(summary)
        self.log(f"📁 Thư mục: {channel_dir}")
        if self.opts.cc_only and ok:
            self.log("   Thông tin ghi công tác giả (bắt buộc với CC BY) đã ghi vào ATTRIBUTION.txt.")
        failed_file = channel_dir / "failed.txt"
        if failures:
            failed_file.write_text("\n".join(failures), encoding="utf-8")
            self.log("   Danh sách video lỗi đã ghi vào failed.txt (chạy lại để thử tải lại).")
        elif failed_file.exists() and not stop_reason:
            failed_file.unlink()  # lần trước có lỗi, lần này đã tải bù xong
        if live:
            self.log("   Video đang/sắp phát trực tiếp sẽ được tải ở lần chạy sau, khi buổi phát đã kết thúc.")
        if stop_exc:
            self.log("\n⛔ " + stop_reason)
            raise stop_exc  # giữ đúng loại lỗi (vd. ExtractorBroken) để giao diện xử lý riêng
        return ok, skipped, failed

    def _process_one(self, ydl, worker: int, idx: int, total: int, vid: str, title: str, url: str, site: str,
                     channel_dir: Path, attribution: Path, c: dict, failures: list[str]):
        """Lấy thông tin, kiểm tra, rồi tải 1 video. Chạy trong luồng tải; cập nhật bộ đếm c (có khoá)."""
        def count(key, failure: str | None = None):
            with self._lock:
                c[key] += 1
                if failure:
                    failures.append(failure)

        self._check_disk(channel_dir, worker=worker)
        try:
            # Lấy thông tin trước, kiểm tra xong mới tải
            info = ydl.extract_info(url, download=False)
            if ydl.in_download_archive(info):  # trang không cho biết mã video lúc lấy danh sách → kiểm tra ở đây
                count("skipped")
                return
            status = info.get("live_status")
            if status in LIVE_STATUSES:
                count("live")
                self.log(f"[{idx}/{total}] ⏭ Bỏ qua ({LIVE_STATUSES[status]}): {title}")
                return
            if self.opts.cc_only and not is_creative_commons(info):
                count("not_cc")
                self.log(f"[{idx}/{total}] ⏭ Bỏ qua (không phải Creative Commons): {title}")
                return
            size = estimate_size(info)
            self._check_disk(channel_dir, size, worker=worker)

            extra = [fmt_size(size)] if size else []
            if self.opts.cc_only:
                extra.append(info["license"])
            self.log(f"[{idx}/{total}] ⬇ {title}" + (f"  ({' · '.join(extra)})" if extra else ""))
            ydl.process_ie_result(info, download=True)
            if self.opts.cc_only:
                # Giấy phép CC BY yêu cầu ghi công tác giả khi dùng lại
                with self._lock, attribution.open("a", encoding="utf-8") as f:
                    f.write(f"{info.get('title')} — {info.get('channel') or info.get('uploader')} — "
                            f"{url} — {info['license']}\n")
            with self._lock:
                c["ok"] += 1
                c["broken"] = 0
        except (Cancelled, StopRun):
            raise
        except yt_dlp.utils.DownloadError as e:
            if isinstance((getattr(e, "exc_info", None) or [None, None])[1], Cancelled):
                raise Cancelled()
            kind = classify_error(str(e))
            if kind == "rate_limit":
                raise StopRun(explain_error(str(e), site))
            if kind == "needs_cookies":  # video nào của trang này cũng sẽ lỗi → dừng và hướng dẫn
                raise StopRun(explain_error(str(e), site))
            if kind == "disk_full":
                self._check_disk(channel_dir, worker=worker)  # báo đúng dung lượng còn lại
                raise StopRun("Ổ đĩa đã đầy. Hãy giải phóng dung lượng rồi chạy lại.")
            if kind == "upcoming":
                count("live")
                self.log(f"[{idx}/{total}] ⏭ Bỏ qua (sắp phát / chưa công chiếu): {title}")
                return
            count("failed", f"{vid}  {title}")
            if kind == "extractor_broken":
                with self._lock:
                    c["broken"] += 1  # đếm chung mọi luồng; có video tải được thì đếm lại từ 0
                    broken = c["broken"]
                if broken >= BROKEN_STREAK:
                    raise ExtractorBroken(
                        f"{BROKEN_STREAK} video liên tiếp tải lỗi theo cùng một kiểu — có vẻ {site} "
                        "vừa thay đổi và phần mềm cần bản cập nhật mới để tải tiếp.")
        except Exception as e:  # tiếp tục với video kế tiếp
            count("failed", f"{vid}  {title}  ({e})")
            self.log(f"   ✖ {e}")


# ====================================================================== GUI

APP_TITLE = "Download Tool"


def eula_dialog(parent, text: str) -> bool:
    """Hộp thoại Điều khoản sử dụng. Trả về True nếu bấm "Tôi đồng ý"."""
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    # Không đặt transient: cửa sổ chính đang ẩn, hộp thoại transient sẽ ẩn theo
    win = tk.Toplevel(parent)
    win.title(f"Điều khoản sử dụng — {APP_TITLE}")
    win.geometry("720x600")
    win.minsize(480, 360)
    result = {"ok": False}
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Vui lòng đọc kỹ Điều khoản sử dụng trước khi dùng phần mềm.",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")
    box = ScrolledText(frm, wrap="word", font=("Segoe UI", 10), padx=8, pady=6)
    box.pack(fill="both", expand=True, pady=(8, 8))
    box.insert("1.0", text)
    box.configure(state="disabled")
    ttk.Label(frm, text="Bấm “Tôi đồng ý” nghĩa là bạn đồng ý với toàn bộ Điều khoản trên, "
                        "trong đó có cam kết chỉ tải nội dung mình có quyền.",
              wraplength=680).pack(anchor="w")

    def agree():
        result["ok"] = True
        win.destroy()

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(10, 0))
    ttk.Button(btns, text="Thoát", command=win.destroy).pack(side="right")
    agree_btn = ttk.Button(btns, text="Tôi đồng ý", command=agree)
    agree_btn.pack(side="right", padx=8)
    agree_btn.focus()

    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.grab_set()
    parent.wait_window(win)
    return result["ok"]


def activation_dialog(parent, trial, expired: bool) -> bool:
    """Hộp thoại nhập mã kích hoạt. Trả về True nếu kích hoạt thành công."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    win = tk.Toplevel(parent)
    win.title("Kích hoạt phần mềm")
    win.resizable(False, False)
    win.transient(parent)
    result = {"ok": False}
    frm = ttk.Frame(win, padding=16)
    frm.pack(fill="both", expand=True)

    head = (f"Đã hết {trial_mod.trial_length_text()} dùng thử trên máy này." if expired else
            f"Bản dùng thử: {trial_mod.remaining_text(trial.remaining)}.")
    ttk.Label(frm, text=head, font=("Segoe UI", 11, "bold")).pack(anchor="w")
    ttk.Label(frm, text="Gửi Mã máy dưới đây cho người bán để nhận mã kích hoạt"
                        + (f" ({trial_mod.CONTACT})" if trial_mod.CONTACT else "") + ":",
              wraplength=460).pack(anchor="w", pady=(10, 4))
    row = ttk.Frame(frm)
    row.pack(fill="x")
    code_var = tk.StringVar(value=trial.code)
    ttk.Entry(row, textvariable=code_var, state="readonly", width=28, font=("Consolas", 11)).pack(side="left")

    def copy_code():
        win.clipboard_clear()
        win.clipboard_append(trial.code)
        copy_btn.configure(text="✓ Đã chép")

    copy_btn = ttk.Button(row, text="Sao chép", command=copy_code)
    copy_btn.pack(side="left", padx=8)

    ttk.Label(frm, text="Mã kích hoạt:").pack(anchor="w", pady=(12, 4))
    key_box = tk.Text(frm, height=4, width=58, font=("Consolas", 10), wrap="char")
    key_box.pack(fill="x")
    key_box.focus()

    def activate():
        if trial.activate(key_box.get("1.0", "end")):
            result["ok"] = True
            messagebox.showinfo("Kích hoạt", "Kích hoạt thành công. Cảm ơn bạn!", parent=win)
            win.destroy()
        else:
            messagebox.showerror("Kích hoạt", "Mã kích hoạt không đúng với máy này.\n"
                                              "Hãy kiểm tra lại, hoặc gửi đúng Mã máy ở trên cho người bán.",
                                 parent=win)

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(12, 0))
    ttk.Button(btns, text="Thoát chương trình" if expired else "Đóng",
               command=win.destroy).pack(side="right")
    ttk.Button(btns, text="Kích hoạt", command=activate).pack(side="right", padx=8)

    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.grab_set()
    parent.wait_window(win)
    return result["ok"]


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title(APP_TITLE)
    # Đồng ý Điều khoản sử dụng trước, để thời gian đọc không bị trừ vào 30 phút dùng thử
    eula_version, eula_text = load_eula()
    if not eula_text:
        root.withdraw()
        messagebox.showerror(APP_TITLE, "Thiếu file Điều khoản sử dụng (EULA.md) nên không thể chạy.\n"
                                        "Hãy cài đặt lại phần mềm.")
        root.destroy()
        return
    if not eula_accepted(eula_version):
        root.withdraw()
        if not eula_dialog(root, eula_text):
            root.destroy()
            return
        accept_eula(eula_version)
        root.deiconify()
    try:
        trial = trial_mod.Trial()
    except trial_mod.StorageError:
        root.withdraw()
        messagebox.showerror(APP_TITLE, "Không ghi được dữ liệu dùng thử trên máy này nên không thể chạy.\n"
                                        "Hãy chạy với tài khoản Windows bình thường (không bị chặn ghi file).")
        root.destroy()
        return
    if trial.expired:
        # Hết dùng thử ngay từ lúc mở: chỉ hiện hộp thoại kích hoạt
        root.withdraw()
        if not activation_dialog(root, trial, expired=True):
            root.destroy()
            return
        root.deiconify()
    root.geometry("800x750")
    root.minsize(620, 460)

    events: queue.Queue = queue.Queue()
    state = {"worker": None, "downloader": None, "updating": False}

    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="Link:").grid(row=0, column=0, sticky="nw", **pad)
    url_box = ttk.Frame(frm)
    url_box.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
    url_var = tk.StringVar()
    url_entry = ttk.Entry(url_box, textvariable=url_var)
    url_entry.pack(fill="x")
    url_entry.focus()
    ttk.Label(url_box, foreground="#666",
              text="Kênh, playlist hoặc 1 video: YouTube, Bilibili, Dailymotion, TikTok, Douyin*, Ixigua*… "
                   "(* cần chọn Cookies trình duyệt)").pack(anchor="w", pady=(2, 0))

    ttk.Label(frm, text="Lưu vào:").grid(row=1, column=0, sticky="w", **pad)
    out_var = tk.StringVar(value=str(default_output_dir()))
    ttk.Entry(frm, textvariable=out_var).grid(row=1, column=1, sticky="ew", **pad)

    def browse():
        d = filedialog.askdirectory(initialdir=out_var.get() or str(Path.home()))
        if d:
            out_var.set(d)

    ttk.Button(frm, text="Chọn…", command=browse).grid(row=1, column=2, **pad)

    opt = ttk.Frame(frm)
    opt.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
    ttk.Label(opt, text="Chất lượng:").pack(side="left")
    q_var = tk.StringVar(value="1080p")
    ttk.Combobox(opt, textvariable=q_var, values=list(QUALITIES), state="readonly", width=18).pack(side="left", padx=(4, 16))
    tab_vars = {k: tk.BooleanVar(value=(k == "videos")) for k in TABS}
    ttk.Label(opt, text="Kênh YouTube:").pack(side="left")
    for k, label in TABS.items():
        ttk.Checkbutton(opt, text=label, variable=tab_vars[k]).pack(side="left", padx=4)
    sub_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(opt, text="Phụ đề", variable=sub_var).pack(side="left", padx=(16, 4))

    opt2 = ttk.Frame(frm)
    opt2.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
    ttk.Label(opt2, text="Cookies (bắt buộc cho Douyin/Ixigua):").pack(side="left")
    COOKIE_FILE_CHOICE = "file cookies.txt…"
    ck_var = tk.StringVar(value="(không)")
    ck_file = {"path": None}
    ck_combo = ttk.Combobox(opt2, textvariable=ck_var, state="readonly", width=16,
                            values=["(không)", "firefox", "chrome", "edge", "brave", "opera", COOKIE_FILE_CHOICE])
    ck_combo.pack(side="left", padx=4)
    ck_file_lbl = ttk.Label(opt2, text="", foreground="#666")
    ck_file_lbl.pack(side="left")

    def on_cookie_choice(_event=None):
        """Chọn “file cookies.txt…” → hỏi file (xuất bằng tiện ích “Get cookies.txt LOCALLY” trên trình duyệt)."""
        if ck_var.get() != COOKIE_FILE_CHOICE:
            ck_file["path"] = None
            ck_file_lbl.configure(text="(nên chọn firefox hoặc file cookies.txt)" if ck_var.get() in
                                  ("chrome", "edge", "brave", "opera") else "")
            return
        path = filedialog.askopenfilename(title="Chọn file cookies.txt (định dạng Netscape)",
                                          filetypes=[("cookies.txt", "*.txt"), ("Tất cả", "*.*")])
        if path:
            ck_file["path"] = path
            ck_file_lbl.configure(text=Path(path).name)
        else:
            ck_var.set("(không)")
            ck_file_lbl.configure(text="")

    ck_combo.bind("<<ComboboxSelected>>", on_cookie_choice)

    opt3 = ttk.Frame(frm)
    opt3.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
    cc_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(opt3, text="Chỉ tải video có giấy phép Creative Commons (được phép dùng lại)",
                    variable=cc_var).pack(anchor="w")
    sleep_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(opt3, text="Nghỉ ngẫu nhiên 2–5 giây giữa các video (giảm nguy cơ bị chặn)",
                    variable=sleep_var).pack(anchor="w")
    tiktok_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(opt3, text="TikTok: dán link 1 video → tải cả kênh của tài khoản đăng video đó",
                    variable=tiktok_var).pack(anchor="w")
    par_row = ttk.Frame(opt3)
    par_row.pack(anchor="w", pady=(2, 0))
    ttk.Label(par_row, text="Số video tải cùng lúc:").pack(side="left")
    par_var = tk.StringVar(value="2")
    ttk.Combobox(par_row, textvariable=par_var, values=["1", "2", "3"], state="readonly",
                 width=3).pack(side="left", padx=4)
    ttk.Label(par_row, text="(2 là nhanh nhất khi đo thử; nhiều hơn dễ bị YouTube chặn)",
              foreground="#666").pack(side="left")

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
    start_btn = ttk.Button(btns, text="▶  Tải về")
    start_btn.pack(side="left")
    stop_btn = ttk.Button(btns, text="■  Dừng", state="disabled")
    stop_btn.pack(side="left", padx=8)
    open_btn = ttk.Button(btns, text="📁 Mở thư mục",
                          command=lambda: os.startfile(out_var.get()) if Path(out_var.get()).exists() else None)
    open_btn.pack(side="right")
    activate_btn = ttk.Button(btns, text="🔑 Kích hoạt")
    if not trial.activated:
        activate_btn.pack(side="right", padx=8)

    overall_lbl = ttk.Label(frm, text="Sẵn sàng.")
    overall_lbl.grid(row=6, column=0, columnspan=3, sticky="w", **pad)
    overall_bar = ttk.Progressbar(frm, mode="determinate")
    overall_bar.grid(row=7, column=0, columnspan=3, sticky="ew", **pad)
    cur_lbl = ttk.Label(frm, text="")
    cur_lbl.grid(row=8, column=0, columnspan=3, sticky="w", **pad)
    cur_bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
    cur_bar.grid(row=9, column=0, columnspan=3, sticky="ew", **pad)

    log_box = ScrolledText(frm, height=12, state="disabled", font=("Consolas", 9))
    log_box.grid(row=10, column=0, columnspan=3, sticky="nsew", **pad)
    frm.rowconfigure(10, weight=1)

    # Dòng trạng thái cập nhật yt-dlp
    upd = ttk.Frame(frm)
    upd.grid(row=11, column=0, columnspan=3, sticky="ew", **pad)
    ver_lbl = ttk.Label(upd, text="")
    ver_lbl.pack(side="left")
    nightly_var = tk.BooleanVar(value=get_channel() == "nightly")
    nightly_chk = ttk.Checkbutton(upd, text="Dùng bản cập nhật thử nghiệm", variable=nightly_var)
    nightly_chk.pack(side="right")
    update_btn = ttk.Button(upd, text="⟳ Kiểm tra cập nhật")
    update_btn.pack(side="right", padx=8)

    def append_log(msg):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def pump():
        try:
            while True:
                kind, *args = events.get_nowait()
                if kind == "log":
                    append_log(args[0])
                elif kind == "overall":
                    done, total, title = args
                    overall_bar.configure(maximum=max(total, 1), value=done)
                    overall_lbl.configure(text=f"Tổng: {done}/{total}" + (f"  —  {title[:80]}" if title else ""))
                elif kind == "progress":
                    pct, speed, eta = args
                    cur_bar.configure(value=pct)
                    cur_lbl.configure(text=f"Đang tải: {pct:5.1f}%   {speed}   còn {eta}" if speed else
                                      f"Đang tải: {pct:5.1f}%")
                elif kind == "alert":
                    messagebox.showwarning("Đã dừng tải", args[0])
                elif kind == "broken":
                    on_broken(args[0])
                elif kind == "update_done":
                    on_update_done(*args)
                elif kind == "done":
                    state["worker"] = None  # luồng tải có thể chưa kịp kết thúc hẳn khi nhận sự kiện này
                    stop_btn.configure(state="disabled")
                    set_idle()
                    if args[0]:
                        append_log(args[0])
        except queue.Empty:
            pass
        root.after(100, pump)

    # ---------- cập nhật yt-dlp ----------

    def downloading() -> bool:
        return bool(state["worker"] and state["worker"].is_alive())

    def set_idle():
        """Bật lại các nút khi không còn tải / cập nhật."""
        busy = downloading() or state["updating"]
        start_btn.configure(state="disabled" if busy else "normal")
        update_btn.configure(state="disabled" if busy else "normal")
        nightly_chk.configure(state="disabled" if busy else "normal")

    def start_update(reason: str, channel: str | None = None):
        """reason: 'startup' | 'manual' | 'channel' | 'broken'"""
        state["updating"] = True
        set_idle()
        ver_lbl.configure(text="⟳ Đang kiểm tra cập nhật…", foreground="")
        if reason == "startup":
            overall_lbl.configure(text="Đang kiểm tra cập nhật, chờ chút…")

        def work():
            try:
                result = update_ytdlp(channel)
            except Exception as e:
                result = UpdateResult(channel or get_channel(), None, None, False, str(e),
                                      "Chưa kiểm tra được cập nhật. Hãy thử lại sau bằng nút “⟳ Kiểm tra cập nhật”.")
            events.put(("update_done", result, reason))

        threading.Thread(target=work, daemon=True).start()

    def on_update_done(result: UpdateResult, reason: str):
        state["updating"] = False
        nightly_var.set(result.channel == "nightly")
        ver_lbl.configure(text=("⚠ " if result.warning else "✓ ") + result.summary(),
                          foreground="#c0392b" if result.warning else "")
        if reason == "startup":
            overall_lbl.configure(text="Sẵn sàng.")
        append_log(result.summary())
        if result.warning:
            append_log("⚠ " + result.warning)
            if reason != "startup" or result.python_too_old:
                messagebox.showwarning("Cập nhật", result.warning)
        set_idle()

        # Bản yt-dlp cũ đã được nạp trong phiên này → phải mở lại chương trình mới dùng được bản mới
        loaded = yt_dlp is not None
        if reason == "broken":
            if result.changed:
                messagebox.showinfo(
                    "Đã có bản cập nhật",
                    f"{result.summary()}\n\nChương trình sẽ mở lại. Sau đó bấm “Tải về” lần nữa — "
                    "video đã tải xong sẽ được bỏ qua.")
                restart_program()
                root.destroy()
            elif not result.warning:
                messagebox.showwarning(
                    "Chưa có bản sửa",
                    "Bạn đang dùng bản mới nhất nhưng bản này chưa kịp sửa lỗi trên.\n"
                    "Bản sửa thường có trong vài ngày — hãy thử lại sau.")
        elif result.changed and loaded and messagebox.askyesno(
                "Đã cập nhật",
                f"{result.summary()}\n\nCần mở lại chương trình để dùng bản mới. Mở lại ngay?"):
            restart_program()
            root.destroy()

    def on_broken(message: str):
        if get_channel() == "stable":
            if messagebox.askyesno(
                    "Trang web vừa thay đổi?",
                    message + "\n\nBản sửa lỗi thường có trong bản cập nhật thử nghiệm trước, "
                    "vài ngày đến vài tuần sau mới có trong bản chính thức.\n\n"
                    "Chuyển sang bản cập nhật thử nghiệm rồi thử lại?\n"
                    "(Có thể quay về bản chính thức bất cứ lúc nào bằng ô “Dùng bản cập nhật thử nghiệm” ở cuối "
                    "cửa sổ.)"):
                start_update("broken", "nightly")
        else:
            append_log("Đang tìm bản cập nhật thử nghiệm mới hơn…")
            start_update("broken", "nightly")

    def on_channel_toggle():
        start_update("channel", "nightly" if nightly_var.get() else "stable")

    update_btn.configure(command=lambda: start_update("manual"))
    nightly_chk.configure(command=on_channel_toggle)

    def start():
        if state["updating"] or downloading():
            return
        try:
            target = resolve_target(url_var.get())
        except ValueError as e:
            messagebox.showerror("Link không hợp lệ", str(e))
            return
        tabs = [k for k, v in tab_vars.items() if v.get()]
        if target.kind == "youtube_channel" and not tabs:
            messagebox.showwarning("Thiếu lựa chọn", "Hãy chọn ít nhất 1 loại: Videos / Shorts / Live.")
            return
        if target.site in COOKIE_SITES and ck_var.get() == "(không)" and not messagebox.askyesno(
                "Cần cookies trình duyệt",
                f"{target.site} thường bắt buộc cookies trình duyệt (không cần đăng nhập).\n\n"
                f"Nên: mở {target.site} bằng Firefox 1 lần rồi chọn “firefox” ở mục Cookies, hoặc xuất "
                "cookies bằng tiện ích “Get cookies.txt LOCALLY” rồi chọn “file cookies.txt…”.\n\n"
                "Vẫn thử tải mà không dùng cookies?", icon="warning", default="no"):
            return
        if not cc_var.get() and not messagebox.askyesno(
                "Xác nhận quyền tải", RIGHTS_NOTICE + "\n\n" + RIGHTS_QUESTION, icon="warning", default="no"):
            return
        opts = Options(
            url=url_var.get(),
            output_dir=Path(out_var.get()),
            quality=QUALITIES[q_var.get()],
            tabs=tabs,
            subtitles=sub_var.get(),
            cookies_browser=None if ck_var.get() in ("(không)", COOKIE_FILE_CHOICE) else ck_var.get(),
            cookies_file=ck_file["path"] if ck_var.get() == COOKIE_FILE_CHOICE else None,
            tiktok_whole_channel=tiktok_var.get(),
            cc_only=cc_var.get(),
            sleep_max=5.0 if sleep_var.get() else 0.0,
            workers=int(par_var.get()),
        )
        dl = ChannelDownloader(
            opts,
            log=lambda m: events.put(("log", m)),
            overall=lambda d, t, title: events.put(("overall", d, t, title)),
            progress=lambda p, s, e: events.put(("progress", p, s, e)),
        )
        state["downloader"] = dl
        log_box.configure(state="normal")
        log_box.delete("1.0", "end")
        log_box.configure(state="disabled")
        stop_btn.configure(state="normal")

        def work():
            msg = ""
            try:
                dl.run()
            except Cancelled:
                msg = "⏹ Đã dừng. Bấm tải lại để tiếp tục — video đã tải xong sẽ được bỏ qua."
            except ExtractorBroken as e:
                events.put(("broken", str(e)))
            except StopRun as e:
                events.put(("alert", str(e)))  # chi tiết đã có trong log
            except Exception as e:
                msg = f"✖ Lỗi: {e}"
            events.put(("done", msg))

        t = threading.Thread(target=work, daemon=True)
        state["worker"] = t
        t.start()
        set_idle()

    def stop():
        if state["downloader"]:
            state["downloader"].cancel()
            stop_btn.configure(state="disabled")
            append_log("… đang dừng sau thao tác hiện tại …")

    start_btn.configure(command=start)
    stop_btn.configure(command=stop)
    url_entry.bind("<Return>", lambda e: start())

    def on_close():
        if state["worker"] and state["worker"].is_alive():
            if not messagebox.askyesno("Đang tải", "Đang tải dở. Thoát luôn?"):
                return
            state["downloader"].cancel()
        trial.tick()  # lưu nốt thời gian đã dùng
        root.destroy()

    # ---------- dùng thử ----------

    def refresh_trial_ui():
        if trial.activated:
            root.title(APP_TITLE)
            activate_btn.pack_forget()
        else:
            root.title(f"{APP_TITLE} — Dùng thử: {trial_mod.remaining_text(trial.remaining)}")

    def on_activate_click():
        activation_dialog(root, trial, expired=False)
        refresh_trial_ui()

    def trial_tick():
        if trial.activated:
            return refresh_trial_ui()
        trial.tick()
        refresh_trial_ui()
        if not trial.expired:
            root.after(5000, trial_tick)
            return
        # Hết giờ dùng thử trong lúc đang mở
        if downloading():
            state["downloader"].cancel()
            append_log("⏹ Đã hết thời gian dùng thử — dừng tải. Video đã tải xong vẫn được giữ.")
        if activation_dialog(root, trial, expired=True):
            refresh_trial_ui()
        else:
            root.destroy()

    activate_btn.configure(command=on_activate_click)
    refresh_trial_ui()
    if not trial.activated:
        root.after(5000, trial_tick)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(100, pump)
    if os.environ.get("YTCD_NO_UPDATE") == "1":  # dùng khi kiểm thử
        ver_lbl.configure(text="(bỏ qua kiểm tra cập nhật)")
    else:
        start_update("startup")
    root.mainloop()


# ====================================================================== CLI

def run_cli(argv):
    # Bộ cài gọi lệnh này để cài thư viện phụ của yt-dlp (trừ mutagen — GPL)
    if argv[:1] == ["--sync-deps"]:
        ok, error = sync_ytdlp_extras()
        print("OK" if ok else f"Lỗi: {error}")
        return 0 if ok else 1
    # Lệnh kích hoạt không cần link kênh
    if argv and argv[0] in ("--machine-code", "--activate"):
        try:
            trial = trial_mod.Trial()
        except trial_mod.StorageError as e:
            print(f"Lỗi: {e}")
            return 2
        if argv[0] == "--machine-code":
            print(trial.code)
            return 0
        if len(argv) < 2:
            print("Cách dùng: run.bat --activate MÃ-KÍCH-HOẠT")
            return 2
        if trial.activate(" ".join(argv[1:])):
            print("Kích hoạt thành công. Cảm ơn bạn!")
            return 0
        print(f"Mã kích hoạt không đúng với máy này (Mã máy: {trial.code}).")
        return 2

    p = argparse.ArgumentParser(
        description="Tải toàn bộ video của 1 kênh YouTube.",
        epilog="Kích hoạt: run.bat --machine-code (xem mã máy) · run.bat --activate MÃ-KÍCH-HOẠT")
    p.add_argument("url", help="Link kênh / playlist / video: YouTube, Bilibili, Dailymotion, TikTok, Douyin, Ixigua…")
    p.add_argument("-o", "--output", default=str(default_output_dir()),
                   help="Thư mục lưu (mặc định: Downloads\\YouTube, hoặc ổ còn trống nhiều nhất nếu ổ đó sắp đầy)")
    p.add_argument("-q", "--quality", default="best",
                   help="best | 2160 | 1440 | 1080 | 720 | 480 | 360 | audio  (mặc định: best)")
    p.add_argument("--shorts", action="store_true", help="Tải cả Shorts")
    p.add_argument("--live", action="store_true", help="Tải cả video Live đã phát")
    p.add_argument("--no-videos", action="store_true", help="Không tải tab Videos thường")
    p.add_argument("--subs", action="store_true", help="Tải phụ đề (vi, en)")
    p.add_argument("--cookies-from-browser", metavar="BROWSER", help="firefox | chrome | edge ...")
    p.add_argument("--cookies", metavar="FILE",
                   help="File cookies.txt (định dạng Netscape, xuất bằng tiện ích “Get cookies.txt LOCALLY”)")
    p.add_argument("--tiktok-channel", action="store_true",
                   help="Với link 1 video TikTok: tải cả kênh của tài khoản đăng video đó")
    p.add_argument("--cc-only", action="store_true",
                   help="Chỉ tải video có giấy phép Creative Commons, bỏ qua các video khác")
    p.add_argument("--i-have-rights", action="store_true",
                   help="Xác nhận bạn có quyền tải nội dung này (bỏ qua câu hỏi xác nhận)")
    p.add_argument("--accept-eula", action="store_true",
                   help="Đồng ý Điều khoản sử dụng trong file EULA.md (bỏ qua câu hỏi đồng ý lần đầu)")
    p.add_argument("--sleep", default="2-5", metavar="MIN-MAX",
                   help="Nghỉ ngẫu nhiên giữa các video, tính bằng giây (mặc định 2-5; 0 = không nghỉ)")
    p.add_argument("--min-free-gb", type=float, default=2.0, metavar="GB",
                   help="Dừng khi ổ đĩa còn trống ít hơn mức này (mặc định 2)")
    p.add_argument("--parallel", type=int, choices=[1, 2, 3], default=2, metavar="N",
                   help="Số video tải cùng lúc: 1, 2 hoặc 3 (mặc định 2)")
    p.add_argument("--no-update", action="store_true", help="Không tự kiểm tra cập nhật trước khi tải")
    p.add_argument("--channel", choices=list(CHANNELS),
                   help="Chọn bản cập nhật: stable (chính thức) hoặc nightly (thử nghiệm). Lựa chọn được ghi nhớ.")
    a = p.parse_args(argv)

    try:
        lo, _, hi = a.sleep.partition("-")
        sleep_min, sleep_max = float(lo), float(hi or lo)
        if sleep_min < 0 or sleep_max < sleep_min:
            raise ValueError
    except ValueError:
        p.error("--sleep phải có dạng MIN-MAX, ví dụ 3-8, hoặc 0 để không nghỉ.")

    # Đồng ý Điều khoản sử dụng trước khi bắt đầu tính giờ dùng thử
    eula_version, eula_text = load_eula()
    if not eula_text:
        print("Lỗi: thiếu file Điều khoản sử dụng (EULA.md). Hãy cài đặt lại phần mềm.")
        return 2
    if not eula_accepted(eula_version):
        if not a.accept_eula:
            print(eula_text + "\n")
            if not sys.stdin or not sys.stdin.isatty():
                print(f"Cần đồng ý Điều khoản sử dụng: đọc file {EULA_FILE.name} rồi thêm --accept-eula.")
                return 2
            try:
                answer = input(EULA_QUESTION + " (y/N): ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in ("y", "yes", "c", "co", "có"):
                print("Đã huỷ. Bạn cần đồng ý Điều khoản sử dụng để dùng phần mềm.")
                return 2
            print()
        accept_eula(eula_version)

    try:
        trial = trial_mod.Trial()
    except trial_mod.StorageError as e:
        print(f"Lỗi: {e}")
        return 2
    if trial.expired:
        print(f"Đã hết {trial_mod.trial_length_text()} dùng thử trên máy này.\n"
              f"Gửi Mã máy cho người bán để nhận mã kích hoạt"
              + (f" ({trial_mod.CONTACT})" if trial_mod.CONTACT else "") + f":  {trial.code}\n"
              "Sau đó chạy:  run.bat --activate MÃ-KÍCH-HOẠT")
        return 5
    if not trial.activated:
        print(f"Bản dùng thử: {trial_mod.remaining_text(trial.remaining)}.\n")

    if not a.cc_only and not a.i_have_rights:
        print(RIGHTS_NOTICE + "\n")
        if not sys.stdin or not sys.stdin.isatty():
            print("Cần xác nhận quyền tải: thêm --i-have-rights, hoặc dùng --cc-only.")
            return 2
        try:
            answer = input(RIGHTS_QUESTION + " (y/N): ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes", "c", "co", "có"):
            print("Đã huỷ.")
            return 2
        print()

    q = a.quality.lower()
    quality = None if q == "best" else ("audio" if q == "audio" else int(q.rstrip("p")))
    tabs = ([] if a.no_videos else ["videos"]) + (["shorts"] if a.shorts else []) + (["streams"] if a.live else [])
    if not tabs:
        p.error("Không có loại video nào được chọn.")

    def progress(pct, speed, eta):
        if speed:
            sys.stdout.write(f"\r   {pct:5.1f}%  {speed:>12}  ETA {eta:>8}   ")
        elif pct >= 100:
            sys.stdout.write("\r" + " " * 50 + "\r")
        sys.stdout.flush()

    if a.no_update:
        if a.channel:
            save_state(channel=a.channel)
    else:
        print("⟳ Đang kiểm tra cập nhật…", flush=True)
        result = update_ytdlp(a.channel)
        print("   " + result.summary())
        if result.warning:
            print("   ⚠ " + result.warning)
        print()

    dl = ChannelDownloader(
        Options(url=a.url, output_dir=Path(a.output), quality=quality, tabs=tabs,
                subtitles=a.subs, cookies_browser=a.cookies_from_browser, cookies_file=a.cookies,
                tiktok_whole_channel=a.tiktok_channel, cc_only=a.cc_only,
                sleep_min=sleep_min, sleep_max=sleep_max, min_free_gb=a.min_free_gb, workers=a.parallel),
        log=lambda m: print(m, flush=True),
        progress=progress,
    )

    # Đếm thời gian dùng thử trong lúc chạy; hết giờ thì dừng tải
    trial_over = threading.Event()
    finished = threading.Event()

    def trial_ticker():
        while not finished.wait(5):
            trial.tick()
            if trial.expired:
                trial_over.set()
                dl.cancel()
                return

    if not trial.activated:
        threading.Thread(target=trial_ticker, daemon=True).start()
    try:
        _, _, failed = dl.run()
    except Cancelled:
        if trial_over.is_set():
            print(f"\n⏹ Đã hết thời gian dùng thử — dừng tải. Video đã tải xong vẫn được giữ.\n"
                  f"Gửi Mã máy cho người bán để nhận mã kích hoạt: {trial.code}\n"
                  "Sau đó chạy:  run.bat --activate MÃ-KÍCH-HOẠT")
            return 5
        return 130
    except ExtractorBroken:
        if get_channel() == "stable":
            print("\nBản sửa lỗi thường có trong bản cập nhật thử nghiệm trước. Thử chạy lại với:\n"
                  f"   run.bat {a.url} --channel nightly\n"
                  "(Quay về bản chính thức sau bằng --channel stable.)")
        else:
            print("\nĐang dùng bản cập nhật thử nghiệm mới nhất nhưng chưa có bản sửa. Hãy thử lại sau vài ngày.")
        return 4
    except StopRun:
        return 3  # lý do đã được in ra trong log
    except KeyboardInterrupt:
        print("\nĐã dừng. Chạy lại để tiếp tục.")
        return 130
    except ValueError as e:
        print(f"Lỗi: {e}")
        return 2
    finally:
        finished.set()
        trial.tick()  # lưu nốt thời gian đã dùng
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()

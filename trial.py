"""
Giới hạn dùng thử 30 phút trên mỗi máy tính + mở khoá vĩnh viễn bằng mã kích hoạt.

- Thời gian dùng thử được CỘNG DỒN trong lúc chương trình đang mở; tắt rồi mở lại vẫn tính tiếp.
- Thời gian đã dùng được lưu ở nhiều nơi (registry + AppData + ProgramData) kèm chữ ký, gắn với
  mã máy. ProgramData dùng chung cho mọi tài khoản Windows trên máy; gỡ cài đặt / cài lại không
  xoá dữ liệu này. Bản ghi bị sửa tay → coi như đã hết hạn.
- Mã kích hoạt là chữ ký Ed25519 của mã máy. Chương trình chỉ chứa KHOÁ CÔNG KHAI nên đọc được
  mã nguồn cũng không tự tạo được mã kích hoạt. Khoá bí mật nằm trong license_tool.py của người bán.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from pathlib import Path

TRIAL_SECONDS = 30 * 60
APP_KEY = "YouTubeChannelDownloader"
CONTACT = ""  # thông tin liên hệ để mua mã kích hoạt (vd. "Zalo 09xx xxx xxx"), hiện trong hộp thoại kích hoạt

# Do license_tool.py init tạo ra — KHÔNG sửa tay
PUBLIC_KEY_HEX = "3439205ddd0a932ccb43ee893923a4e73217da7524899b84ff6bf7d9400dea05"
_SEAL = bytes.fromhex("4bf1b5a774e4c93cfaa77b9dbc31dbe188f45b232b65b42b7fa46e1eee479c7e")

REG_PATH = r"Software\YouTubeChannelDownloader"
REG_VALUE = "license"
USE_REGISTRY = sys.platform == "win32"


def file_stores() -> list[Path]:
    """Các file lưu dữ liệu dùng thử (ngoài thư mục cài đặt nên gỡ cài đặt không mất)."""
    stores = []
    for var in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(var)
        if base:
            stores.append(Path(base) / APP_KEY / "license.dat")
    return stores


# ---------------------------------------------------------------- mã máy

def _machine_guid() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                 winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            return winreg.QueryValueEx(key, "MachineGuid")[0]
        except OSError:
            pass
    import platform
    import uuid
    return f"{uuid.getnode():x}-{platform.node()}"


def machine_code() -> str:
    """Mã máy dạng XXXX-XXXX-XXXX-XXXX, người dùng gửi cho người bán để nhận mã kích hoạt."""
    digest = hashlib.sha256(b"ytcd-machine:" + _machine_guid().encode()).digest()[:10]
    raw = base64.b32encode(digest).decode()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------- mã kích hoạt

def _activation_message(code: str) -> bytes:
    return b"ytcd-activate:" + code.encode()


def normalize_key(key: str) -> str:
    return "".join(ch for ch in key.upper() if ch.isalnum())


def format_key(raw: str) -> str:
    raw = normalize_key(raw)
    return "-".join(raw[i:i + 8] for i in range(0, len(raw), 8))


def verify_activation(code: str, key: str) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    raw = normalize_key(key)
    try:
        signature = base64.b32decode(raw + "=" * (-len(raw) % 8))
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(
            signature, _activation_message(code))
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


# ---------------------------------------------------------------- lưu trữ

def _seal(code: str, used: float, key: str) -> str:
    msg = json.dumps([code, round(used, 1), key], separators=(",", ":")).encode()
    return hmac.new(_SEAL, msg, hashlib.sha256).hexdigest()


def _encode(code: str, used: float, key: str) -> str:
    record = {"m": code, "u": round(used, 1), "k": key, "s": _seal(code, used, key)}
    return base64.b64encode(json.dumps(record).encode()).decode()


def _decode(text: str, code: str) -> tuple[float, str] | None:
    """(đã dùng, mã kích hoạt) nếu bản ghi hợp lệ; (TRIAL_SECONDS, "") nếu bị sửa; None nếu của máy khác."""
    try:
        record = json.loads(base64.b64decode(text))
        used, key, mcode = float(record["u"]), str(record.get("k", "")), record["m"]
        valid = hmac.compare_digest(record["s"], _seal(mcode, used, key))
    except Exception:
        return float(TRIAL_SECONDS), ""  # hỏng / bị sửa → coi như hết hạn
    if not valid:
        return float(TRIAL_SECONDS), ""
    if mcode != code:
        return None  # chép từ máy khác sang: bỏ qua
    return used, key


def _read_all(code: str) -> list[tuple[float, str]]:
    records = []
    if USE_REGISTRY:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
                records.append(_decode(winreg.QueryValueEx(k, REG_VALUE)[0], code))
        except OSError:
            pass
    for path in file_stores():
        try:
            records.append(_decode(path.read_text(encoding="ascii"), code))
        except OSError:
            pass
    return [r for r in records if r is not None]


def _write_all(code: str, used: float, key: str) -> int:
    """Ghi vào mọi nơi lưu; trả về số nơi ghi thành công."""
    data, written = _encode(code, used, key), 0
    if USE_REGISTRY:
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
                winreg.SetValueEx(k, REG_VALUE, 0, winreg.REG_SZ, data)
            written += 1
        except OSError:
            pass
    for path in file_stores():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data, encoding="ascii")
            written += 1
        except OSError:
            pass
    return written


class StorageError(Exception):
    """Không ghi được dữ liệu dùng thử ở bất kỳ đâu (chặn cách lách bằng file chỉ-đọc)."""


class Trial:
    def __init__(self):
        self.code = machine_code()
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self.used, self.key = self._load()
        self.activated = bool(self.key) and verify_activation(self.code, self.key)
        if not self.activated and _write_all(self.code, self.used, self.key) == 0:
            raise StorageError("Không ghi được dữ liệu dùng thử trên máy này.")

    def _load(self) -> tuple[float, str]:
        records = _read_all(self.code)
        used = max((u for u, _ in records), default=0.0)
        key = next((k for _, k in records if k and verify_activation(self.code, k)), "")
        return used, key

    @property
    def remaining(self) -> float:
        return float("inf") if self.activated else max(0.0, TRIAL_SECONDS - self.used)

    @property
    def expired(self) -> bool:
        return not self.activated and self.used >= TRIAL_SECONDS

    def tick(self) -> float:
        """Cộng thời gian đã mở kể từ lần gọi trước vào bộ đếm và lưu lại. Trả về số giây còn lại.
        Đọc lại trước khi cộng để nhiều cửa sổ cùng mở vẫn cộng dồn đúng."""
        with self._lock:
            now = time.monotonic()
            delta, self._last = now - self._last, now
            if self.activated:
                return self.remaining
            stored, key = self._load()
            if key:  # kích hoạt từ cửa sổ khác
                self.key, self.activated = key, True
                return self.remaining
            self.used = max(stored, self.used) + delta
            _write_all(self.code, self.used, "")
            return self.remaining

    def activate(self, key: str) -> bool:
        key = format_key(key)
        if not verify_activation(self.code, key):
            return False
        with self._lock:
            self.key, self.activated = key, True
            _write_all(self.code, self.used, key)
        return True


def trial_length_text() -> str:
    return f"{TRIAL_SECONDS // 60} phút" if TRIAL_SECONDS >= 60 else f"{TRIAL_SECONDS} giây"


def remaining_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"còn {minutes} phút" if minutes >= 1 else f"còn {int(seconds)} giây"

"""
Tool CỦA NGƯỜI BÁN — tạo mã kích hoạt. KHÔNG đưa file này và license_private_key.pem cho người dùng.

  python license_tool.py init                    Tạo cặp khoá lần đầu (ghi khoá công khai vào trial.py)
  python license_tool.py make XXXX-XXXX-XXXX-XXXX Tạo mã kích hoạt cho 1 mã máy
  python license_tool.py machine-code            Xem mã máy của máy này
  python license_tool.py reset-trial             Xoá dữ liệu dùng thử trên máy này (để tự kiểm tra)

Giữ kỹ và SAO LƯU license_private_key.pem: mất file này thì không tạo được mã kích hoạt cho các
bản đã phát hành; lộ file này thì ai cũng tự tạo được mã kích hoạt.
"""

from __future__ import annotations

import argparse
import base64
import re
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent
PRIVATE_KEY = ROOT / "license_private_key.pem"
TRIAL_PY = ROOT / "trial.py"

sys.path.insert(0, str(ROOT))
import trial  # noqa: E402


def load_private_key() -> Ed25519PrivateKey:
    if not PRIVATE_KEY.exists():
        sys.exit(f"Chưa có {PRIVATE_KEY.name}. Chạy: python license_tool.py init")
    return serialization.load_pem_private_key(PRIVATE_KEY.read_bytes(), password=None)


def cmd_init(force: bool):
    if PRIVATE_KEY.exists() and not force:
        sys.exit(f"{PRIVATE_KEY.name} đã có. Tạo lại sẽ làm MỌI mã kích hoạt đã phát ra mất hiệu lực "
                 "ở bản phát hành mới. Nếu chắc chắn, chạy lại với --force.")
    key = Ed25519PrivateKey.generate()
    PRIVATE_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    public_hex = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    source = TRIAL_PY.read_text(encoding="utf-8")
    source = re.sub(r'PUBLIC_KEY_HEX = "[0-9a-f]+"', f'PUBLIC_KEY_HEX = "{public_hex}"', source)
    source = re.sub(r'_SEAL = bytes\.fromhex\("[0-9a-f]+"\)', f'_SEAL = bytes.fromhex("{secrets.token_hex(32)}")',
                    source)
    TRIAL_PY.write_text(source, encoding="utf-8")
    print(f"Đã tạo {PRIVATE_KEY.name} và ghi khoá công khai vào {TRIAL_PY.name}.")
    print("→ Hãy SAO LƯU license_private_key.pem ở nơi an toàn, rồi đóng gói lại file cài đặt.")


def cmd_make(code: str):
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}", code):
        sys.exit("Mã máy không hợp lệ (dạng XXXX-XXXX-XXXX-XXXX).")
    signature = load_private_key().sign(trial._activation_message(code))
    key = trial.format_key(base64.b32encode(signature).decode().rstrip("="))
    assert trial.verify_activation(code, key), "Khoá công khai trong trial.py không khớp khoá bí mật!"
    print(f"Mã máy:        {code}")
    print(f"Mã kích hoạt:  {key}")


def cmd_reset():
    removed = []
    if trial.USE_REGISTRY:
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, trial.REG_PATH)
            removed.append("registry")
        except OSError:
            pass
    for path in trial.file_stores():
        if path.exists():
            path.unlink()
            removed.append(str(path))
    print("Đã xoá: " + (", ".join(removed) if removed else "(không có gì)"))


def main():
    p = argparse.ArgumentParser(description="Tool tạo mã kích hoạt (chỉ dành cho người bán).")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="Tạo cặp khoá lần đầu")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("make", help="Tạo mã kích hoạt cho 1 mã máy")
    s.add_argument("machine_code")
    sub.add_parser("machine-code", help="Xem mã máy của máy này")
    sub.add_parser("reset-trial", help="Xoá dữ liệu dùng thử trên máy này")
    a = p.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "init":
        cmd_init(a.force)
    elif a.cmd == "make":
        cmd_make(a.machine_code)
    elif a.cmd == "machine-code":
        print(trial.machine_code())
    else:
        cmd_reset()


if __name__ == "__main__":
    main()

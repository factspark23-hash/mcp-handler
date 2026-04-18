"""Post-install funding prompt. Shows once, can be dismissed forever."""
import os
import sys
import json
from pathlib import Path

SPONSOR_URL = "https://github.com/sponsors/factspark23-hash"
MARKER_FILE = ".mcp-hub-funding-dismissed"


def _get_marker_path() -> Path:
    """Store dismiss flag in user's home config."""
    config_dir = Path.home() / ".config" / "mcp-hub"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / MARKER_FILE


def is_dismissed() -> bool:
    return _get_marker_path().exists()


def dismiss():
    _get_marker_path().write_text("dismissed")
    print("\n  ✓ Funding prompt dismissed. Won't show again.\n")


def show():
    """Render QR code + funding message in terminal."""
    try:
        import qrcode
    except ImportError:
        print(f"\n  ☕ Support MCP Hub: {SPONSOR_URL}\n")
        return

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=2,
    )
    qr.add_data(SPONSOR_URL)
    qr.make(fit=True)

    # ANSI colors
    W = "\033[0m"      # reset
    B = "\033[47m\033[30m"  # white bg, black fg (for QR white modules)
    D = "\033[40m\033[37m"  # black bg, white fg (for QR dark modules)
    DIM = "\033[2m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"

    print()
    print(f"  {BOLD}{CYAN}╔══════════════════════════════════════════════╗{W}")
    print(f"  {BOLD}{CYAN}║          ☕  SUPPORT MCP HUB  ☕             ║{W}")
    print(f"  {BOLD}{CYAN}╚══════════════════════════════════════════════╝{W}")
    print()

    # Render QR code as block characters
    matrix = qr.get_matrix()
    lines = []
    for row_idx in range(0, len(matrix), 2):
        line = f"  {BOLD}  {W}"  # left padding
        for col in range(len(matrix[0])):
            top = matrix[row_idx][col]
            bottom = matrix[row_idx + 1][col] if row_idx + 1 < len(matrix) else False
            if top and bottom:
                line += f"{D} {W}"  # full block dark
            elif top:
                line += f"{D}▄{W}"  # upper half dark
            elif bottom:
                line += f"{D}▀{W}"  # lower half dark
            else:
                line += f" "  # empty
        lines.append(line)

    # Print QR with borders
    width = len(matrix[0]) + 4
    print(f"  {D}{' ' * width}{W}")
    for line in lines:
        print(line)
    print(f"  {D}{' ' * width}{W}")

    print()
    print(f"  {BOLD}If you are able to pay, scan this QR code.{W}")
    print(f"  {DIM}If you are not, use this free forever. No pressure.{W}")
    print()
    print(f"  {YELLOW}We are raising funds for our second project.{W}")
    print(f"  {DIM}{SPONSOR_URL}{W}")
    print()
    print(f"  {DIM}To dismiss forever: mcp-hub --dismiss-funding{W}")
    print()


if __name__ == "__main__":
    if "--dismiss" in sys.argv:
        dismiss()
    elif not is_dismissed():
        show()

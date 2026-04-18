"""Post-install funding prompt. Shows once, can be dismissed forever."""
import os
import sys
import base64
from pathlib import Path

SPONSOR_URL = "https://github.com/sponsors/factspark23-hash"
USDT_ADDRESS = "0xAba97613C0055E98830B6d1C9eB62c459024f4D5"
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


def _render_qr_ascii(url: str) -> list[str]:
    """Render QR code as ASCII art in terminal."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        matrix = qr.get_matrix()
        lines = []
        for row_idx in range(0, len(matrix), 2):
            line = ""
            for col in range(len(matrix[0])):
                top = matrix[row_idx][col]
                bottom = matrix[row_idx + 1][col] if row_idx + 1 < len(matrix) else False
                if top and bottom:
                    line += "█"
                elif top:
                    line += "▀"
                elif bottom:
                    line += "▄"
                else:
                    line += " "
            lines.append(line)
        return lines
    except ImportError:
        return [f"  [Install qrcode to see QR: {url}]"]


def show():
    """Render QR codes + funding message in terminal."""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    WHITE = "\033[97m"
    RESET = "\033[0m"

    # Generate QR codes
    github_qr = _render_qr_ascii(SPONSOR_URL)
    usdt_qr = _render_qr_ascii(USDT_ADDRESS)

    print()
    print(f"  {BOLD}{CYAN}{'═' * 56}{RESET}")
    print(f"  {BOLD}{CYAN}║{RESET}        {BOLD}☕  FUND MCP HUB — SUPPORT US  ☕{RESET}        {BOLD}{CYAN}║{RESET}")
    print(f"  {BOLD}{CYAN}{'═' * 56}{RESET}")
    print()

    # Message
    print(f"  {BOLD}We are raising funds for our second project:{RESET}")
    print(f"  {YELLOW}  → A browser made only for AI Agents{RESET}")
    print(f"  {DIM}    (not for humans — designed for autonomous browsing){RESET}")
    print()
    print(f"  {DIM}MCP Hub is free and always will be.{RESET}")
    print(f"  {DIM}If you can afford to pay, please do.{RESET}")
    print(f"  {DIM}If you can't, use it freely. No pressure.{RESET}")
    print()

    # Two QR codes side by side
    print(f"  {BOLD}{'─' * 56}{RESET}")

    # Calculate padding for side-by-side display
    github_width = max(len(line) for line in github_qr) if github_qr else 0
    usdt_width = max(len(line) for line in usdt_qr) if usdt_qr else 0
    gap = 6
    max_lines = max(len(github_qr), len(usdt_qr))

    # Headers
    gh_label = "GitHub Sponsors"
    usdt_label = "USDT (ERC20)"
    gh_center = (github_width - len(gh_label)) // 2
    usdt_center = (usdt_width - len(usdt_label)) // 2
    print(f"  {GREEN}{BOLD}{' ' * gh_center}{gh_label}{' ' * (github_width - gh_center - len(gh_label))}{' ' * gap}{MAGENTA}{BOLD}{' ' * usdt_center}{usdt_label}{RESET}")

    # QR codes
    for i in range(max_lines):
        gh_line = github_qr[i] if i < len(github_qr) else " " * github_width
        usdt_line = usdt_qr[i] if i < len(usdt_qr) else " " * usdt_width
        print(f"  {GREEN}{gh_line}{' ' * (github_width - len(gh_line))}{' ' * gap}{MAGENTA}{usdt_line}{RESET}")

    print(f"  {BOLD}{'─' * 56}{RESET}")
    print()

    # URLs/addresses below QR
    print(f"  {GREEN}{DIM}GitHub:{RESET} {DIM}{SPONSOR_URL}{RESET}")
    print(f"  {MAGENTA}{DIM}USDT:{RESET}  {DIM}{USDT_ADDRESS}{RESET}")
    print()

    # How GitHub Sponsors works
    print(f"  {BOLD}How GitHub Sponsors works:{RESET}")
    print(f"  {DIM}  1. Click the QR code or visit the link above{RESET}")
    print(f"  {DIM}  2. Sign in with your GitHub account{RESET}")
    print(f"  {DIM}  3. Choose one-time or monthly sponsorship{RESET}")
    print(f"  {DIM}  4. Pay via credit card / PayPal / GitHub balance{RESET}")
    print(f"  {DIM}  5. 100% goes to the developer (no platform cut){RESET}")
    print()

    print(f"  {DIM}To dismiss forever: mcp-hub --dismiss-funding{RESET}")
    print()


if __name__ == "__main__":
    if "--dismiss" in sys.argv:
        dismiss()
    elif not is_dismissed():
        show()

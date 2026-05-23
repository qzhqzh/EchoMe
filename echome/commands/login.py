"""Login/logout/whoami commands for multi-user authentication."""

import http.server
import threading
import urllib.parse
import webbrowser

import typer
from rich.console import Console

from echome.core.config import Config

console = Console()

# Local callback server state
_received_token: str | None = None
_server_event = threading.Event()


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler to capture the JWT from browser redirect."""

    def do_GET(self) -> None:
        global _received_token
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        token = params.get("token", [None])[0]
        if token:
            _received_token = token
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>&#10004; Login successful!</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
            _server_event.set()
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Missing token</h2></body></html>")

    def log_message(self, format, *args) -> None:
        """Suppress server logs."""
        pass


def login(
    browser: bool = typer.Option(False, "--browser", "-b", help="Use browser flow (requires GUI desktop)"),
    manual: bool = typer.Option(False, "--manual", "-m", help="(deprecated, now default) Paste token manually"),
    hub: str = typer.Option("", "--hub", help="Hub URL (default: from config or https://echome.qzhqzh.com)"),
) -> None:
    """Login via GitHub OAuth. Default: open URL, copy token, paste back."""
    global _received_token
    _received_token = None

    config = Config.load()

    # Allow overriding hub URL
    if hub.strip():
        config.hub_url = hub.strip().rstrip("/")
        config.save()

    hub_url = config.hub_url.rstrip("/")

    if browser:
        # Browser flow with local callback server (for GUI desktops)
        _login_browser(config, hub_url)
        return

    # Default: manual/token-paste flow (works on any Linux)
    console.print("\n[bold]EchoMe Login[/bold]\n")

    # Direct user to the CLI-friendly login page
    cli_login_url = f"{hub_url}/login?source=cli"

    console.print("  1. Open this URL in your browser:\n")
    console.print(f"     [cyan]{cli_login_url}[/cyan]\n")
    console.print("  2. Click [bold]Login with GitHub[/bold] and authorize")
    console.print("  3. Copy the token shown on the page\n")

    # Allow retrying if token is wrong
    while True:
        token = typer.prompt("Paste token here")
        if not token.strip():
            console.print("[red]No token provided.[/red]")
            raise typer.Exit(1)

        # Strip common accidental prefixes (e.g. "$ " from copy-paste)
        cleaned = token.strip()
        if cleaned.startswith("$ "):
            cleaned = cleaned[2:]

        config.token = cleaned
        config.save()

        # Verify the token works
        try:
            _verify_and_show_user(config)
            console.print("[green]✓ Login successful![/green]\n")
            return
        except SystemExit:
            # _verify_and_show_user calls typer.Exit on failure
            console.print("[yellow]Token invalid or expired. Try again (Ctrl+C to quit).[/yellow]\n")
            config.token = ""
            config.save()
            continue


def _login_browser(config: Config, hub_url: str) -> None:
    """Browser-based login with local callback server (for GUI desktops)."""
    global _received_token
    console.print("\n[bold]GitHub OAuth Login (Browser)[/bold]\n")

    port = 19876
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    auth_url = f"{hub_url}/api/v1/auth/github"
    console.print(f"Opening browser to: [cyan]{auth_url}[/cyan]")
    console.print(f"[dim]Waiting for callback on http://127.0.0.1:{port} ...[/dim]\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        console.print("[yellow]Could not open browser.[/yellow]")
        console.print("Try: [cyan]echome login[/cyan] (default token-paste flow)\n")

    if _server_event.wait(timeout=120):
        server.shutdown()
        if _received_token:
            config.token = _received_token
            config.save()
            console.print("[green]✓ Login successful![/green]\n")
            _verify_and_show_user(config)
        else:
            console.print("[red]✗ Failed to receive token.[/red]")
            raise typer.Exit(1)
    else:
        server.shutdown()
        console.print("[red]✗ Timeout.[/red] Try: [cyan]echome login[/cyan]\n")
        raise typer.Exit(1)


def logout() -> None:
    """Clear saved JWT token."""
    config = Config.load()
    if not config.token:
        console.print("[dim]Not logged in.[/dim]")
        return
    config.token = ""
    config.save()
    console.print("[green]✓ Logged out.[/green]\n")


def whoami() -> None:
    """Show current user info."""
    config = Config.load()
    if not config.token:
        console.print("[yellow]Not logged in.[/yellow] Run: [cyan]echome login[/cyan]\n")
        raise typer.Exit(1)
    _verify_and_show_user(config)


def _verify_and_show_user(config: Config) -> None:
    """Verify token and display user info. Raises typer.Exit(1) on failure."""
    from echome.core.client import HubClient

    try:
        client = HubClient(config)
        with client._client() as http_client:
            resp = http_client.get("/api/v1/auth/me")
            resp.raise_for_status()
            user = resp.json()

        console.print(f"  User:  [bold]{user['username']}[/bold]")
        console.print(f"  Role:  {user['role']}")
        console.print(f"  Hub:   {config.hub_url}")
        console.print()
    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[red]✗ Verification failed:[/red] {e}")
        raise typer.Exit(1) from e

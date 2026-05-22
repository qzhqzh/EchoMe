"""Login/logout/whoami commands for multi-user authentication."""

import http.server
import threading
import time
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
    manual: bool = typer.Option(False, "--manual", "-m", help="Manually paste token instead of browser flow"),
    hub: str = typer.Option("", "--hub", help="Hub URL (default: from config or https://echome.qzhqzh.com)"),
) -> None:
    """Login via GitHub OAuth. Opens browser for authorization."""
    global _received_token
    _received_token = None

    config = Config.load()

    # Allow overriding hub URL
    if hub.strip():
        config.hub_url = hub.strip().rstrip("/")
        config.save()

    if manual:
        # Simple manual flow: user copies token from web UI
        hub = config.hub_url.rstrip("/")
        console.print("\n[bold]Manual Login (for servers without GUI)[/bold]\n")
        console.print("Steps:")
        console.print(f"  1. On any device with a browser, open:")
        console.print(f"     [cyan]{hub}/api/v1/auth/github[/cyan]")
        console.print(f"  2. Click the GitHub authorization URL in the response")
        console.print(f"  3. After authorizing, you'll get a JSON response")
        console.print(f"  4. Copy the [bold]access_token[/bold] value from the JSON\n")
        console.print("[dim]Tip: The JSON looks like: {\"access_token\": \"eyJhbG...\", ...}[/dim]\n")

        token = typer.prompt("Paste your access_token here")
        if not token.strip():
            console.print("[red]No token provided.[/red]")
            raise typer.Exit(1)

        config.token = token.strip()
        config.save()
        console.print("[green]✓ Token saved![/green]\n")

        # Verify
        _verify_and_show_user(config)
        return

    # Browser flow with local callback server
    console.print("\n[bold]GitHub OAuth Login[/bold]\n")

    # Start local callback server
    port = 19876
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Open browser to Hub's GitHub auth
    auth_url = f"{config.hub_url}/api/v1/auth/github"
    console.print(f"Opening browser to: [cyan]{auth_url}[/cyan]")
    console.print(f"[dim]Waiting for callback on http://127.0.0.1:{port} ...[/dim]\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        console.print(f"[yellow]Could not open browser. Please open manually:[/yellow]")
        console.print(f"  [cyan]{auth_url}[/cyan]\n")

    # Wait for callback (up to 120 seconds)
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
        console.print("[red]✗ Timeout waiting for login callback.[/red]")
        console.print("Try [cyan]echome login --manual[/cyan] instead.\n")
        raise typer.Exit(1)


def logout() -> None:
    """Clear saved JWT token and logout."""
    config = Config.load()
    if not config.token:
        console.print("[dim]Not logged in.[/dim]")
        return

    config.token = ""
    config.save()
    console.print("[green]✓ Logged out.[/green] Token cleared from ~/.echome/config.yaml\n")


def whoami() -> None:
    """Show current logged-in user info."""
    config = Config.load()
    if not config.token:
        console.print("[yellow]Not logged in.[/yellow] Run [cyan]echome login[/cyan] to authenticate.\n")
        raise typer.Exit(1)

    _verify_and_show_user(config)


def _verify_and_show_user(config: Config) -> None:
    """Verify token with Hub and display user info."""
    from echome.core.client import HubClient

    try:
        client = HubClient(config)
        with client._client() as http_client:
            resp = http_client.get("/api/v1/auth/me")
            resp.raise_for_status()
            user = resp.json()

        console.print(f"  [bold]User:[/bold]     {user['username']}")
        console.print(f"  [bold]Role:[/bold]     {user['role']}")
        if user.get("email"):
            console.print(f"  [bold]Email:[/bold]    {user['email']}")
        console.print(f"  [bold]Hub:[/bold]      {config.hub_url}")
        console.print()
    except Exception as e:
        console.print(f"[red]✗ Token verification failed:[/red] {e}")
        console.print("Try [cyan]echome login[/cyan] to re-authenticate.\n")
        raise typer.Exit(1)

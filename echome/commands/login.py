"""Login/logout/whoami commands for multi-user authentication."""

import http.server
import threading
import urllib.parse
import webbrowser

import httpx
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

    hub_url = config.hub_url.rstrip("/")

    if manual:
        console.print("\n[bold]Manual Login[/bold]\n")

        # Verify Hub is reachable
        console.print(f"[dim]Checking Hub at {hub_url} ...[/dim]")
        try:
            resp = httpx.get(f"{hub_url}/health", timeout=10)
            resp.raise_for_status()
        except Exception as e:
            console.print(f"[red]Failed to connect to Hub:[/red] {e}")
            console.print(f"Check that Hub is running at: {hub_url}")
            raise typer.Exit(1)

        # Direct user to the CLI-friendly login page
        cli_login_url = f"{hub_url}/login?source=cli"

        console.print(f"  1. Open this URL in your browser:\n")
        console.print(f"     [cyan]{cli_login_url}[/cyan]\n")
        console.print(f"  2. Click [bold]Login with GitHub[/bold] and authorize")
        console.print(f"  3. Copy the token shown on the page\n")

        token = typer.prompt("Paste token here")
        if not token.strip():
            console.print("[red]No token provided.[/red]")
            raise typer.Exit(1)

        config.token = token.strip()
        config.save()
        console.print("[green]✓ Saved![/green]\n")
        _verify_and_show_user(config)
        return

    # Browser flow with local callback server
    console.print("\n[bold]GitHub OAuth Login[/bold]\n")

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
        console.print(f"[yellow]Could not open browser.[/yellow]")
        console.print(f"Try: [cyan]echome login --manual[/cyan]\n")

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
        console.print("[red]✗ Timeout.[/red] Try: [cyan]echome login --manual[/cyan]\n")
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
    """Verify token and display user info."""
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
    except Exception as e:
        console.print(f"[red]✗ Verification failed:[/red] {e}")
        console.print("Try: [cyan]echome login[/cyan]\n")
        raise typer.Exit(1)

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

import config
from queue.database import Database
from queue.models import Post, PostStatus, Platform
from scraper.depop_scraper import DepopScraper
from captions.generator import CaptionGenerator
from publishers.pinterest import PinterestPublisher
from publishers.instagram import InstagramPublisher
from auth.pinterest_oauth import PinterestOAuth

console = Console()


def get_db() -> Database:
    return Database(config.DATABASE_PATH)


@click.group()
def cli():
    """Social Media Agent - Automate social posts for your reselling business."""
    pass


@cli.command()
def setup():
    """Log in to Crosslist (one-time setup). Opens a browser for you to sign in."""
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    profile_dir = str(Path(config.IMAGE_DOWNLOAD_DIR).parent / "browser_profile")

    console.print("[bold]Crosslist Login Setup[/bold]")
    console.print("A browser window will open to Crosslist.")
    console.print("Log in with your account — your session will be saved for future scrapes.\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://app.crosslist.com/", timeout=60000)

        console.print("[dim]Waiting for login... (sign in with your Crosslist account)[/dim]")

        try:
            for _ in range(120):
                import time
                time.sleep(1)
                url = page.url.lower()
                if "login" not in url and "signin" not in url and "sign-in" not in url:
                    console.print(f"[green]Success![/green] Logged in. Session saved.")
                    console.print("You can now run 'scrape' to pull your listings.")
                    page.wait_for_timeout(3000)
                    break
        except Exception:
            pass

        context.close()


@cli.command()
def scrape():
    """Scrape listings from your Crosslist dashboard."""
    console.print("Scraping listings from [bold]Crosslist[/bold]...")

    scraper = DepopScraper()
    listings = scraper.scrape_shop()
    scraper.close()

    if not listings:
        console.print("[yellow]No listings found.[/yellow]")
        console.print("  Make sure you're logged in. Run [bold]python main.py setup[/bold] first.")
        return

    db = get_db()
    new_count = 0
    for listing in listings:
        if db.save_listing(listing):
            new_count += 1
    db.close()

    console.print(f"[green]Done![/green] Found {len(listings)} listings, {new_count} new.")


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["pinterest", "instagram"]), default="pinterest")
@click.option("--use-ai/--no-ai", default=True, help="Use Claude AI for captions (default: yes)")
def generate(platform: str, use_ai: bool):
    """Generate social media captions for unprocessed listings."""
    plat = Platform(platform)
    db = get_db()
    listings = db.get_unprocessed_listings(plat)

    if not listings:
        console.print(f"[yellow]No unprocessed listings for {platform}.[/yellow] Run 'scrape' first.")
        db.close()
        return

    console.print(f"Generating {platform} captions for {len(listings)} listings...")

    generator = None
    if use_ai and config.ANTHROPIC_API_KEY:
        generator = CaptionGenerator(config.ANTHROPIC_API_KEY)
    elif use_ai:
        console.print("[yellow]Warning:[/yellow] ANTHROPIC_API_KEY not set. Using fallback captions.")

    for listing in listings:
        if generator:
            caption = generator.generate(listing, plat)
        else:
            caption = CaptionGenerator("")._fallback_caption(listing, plat)

        post = Post(
            listing_id=listing.id,
            platform=plat,
            caption=caption,
            image_urls=listing.images,
            destination_url=listing.url,
        )
        db.add_post(post)
        console.print(f"  [dim]Generated:[/dim] {listing.title[:50]}")

    db.close()
    console.print(f"[green]Done![/green] Generated {len(listings)} draft posts. Run 'review' to approve them.")


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["pinterest", "instagram", "all"]), default="all")
def review(platform: str):
    """Review and approve/reject draft posts."""
    db = get_db()
    plat = Platform(platform) if platform != "all" else None
    drafts = db.get_posts(status=PostStatus.DRAFT, platform=plat)

    if not drafts:
        console.print("[yellow]No drafts to review.[/yellow]")
        db.close()
        return

    console.print(f"\n[bold]Reviewing {len(drafts)} draft posts:[/bold]\n")

    for post in drafts:
        listing = db.get_listing(post.listing_id)
        title = listing.title if listing else post.listing_id

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()
        table.add_row("ID", str(post.id))
        table.add_row("Listing", title[:60])
        table.add_row("Platform", post.platform.value)
        table.add_row("Image", post.image_urls[0][:80] + "..." if post.image_urls else "None")
        table.add_row("Link", post.destination_url)
        console.print(table)
        console.print(f"\n[bold]Caption:[/bold]\n{post.caption}\n")

        action = Prompt.ask(
            "[a]pprove / [r]eject / [e]dit / [s]kip / [q]uit",
            choices=["a", "r", "e", "s", "q"],
            default="s",
        )

        if action == "a":
            db.approve_post(post.id)
            console.print("[green]Approved![/green]\n")
        elif action == "r":
            db.reject_post(post.id)
            console.print("[red]Rejected (deleted).[/red]\n")
        elif action == "e":
            new_caption = Prompt.ask("Enter new caption")
            db.update_caption(post.id, new_caption)
            db.approve_post(post.id)
            console.print("[green]Updated and approved![/green]\n")
        elif action == "q":
            break

    db.close()


@cli.command()
@click.option("--platform", "-p", type=click.Choice(["pinterest", "instagram"]), default="pinterest")
def publish(platform: str):
    """Publish all approved posts to the specified platform."""
    plat = Platform(platform)
    db = get_db()
    posts = db.get_posts(status=PostStatus.APPROVED, platform=plat)

    if not posts:
        console.print(f"[yellow]No approved posts for {platform}.[/yellow] Run 'review' first.")
        db.close()
        return

    # Initialize publisher
    if plat == Platform.PINTEREST:
        if not config.PINTEREST_ACCESS_TOKEN or not config.PINTEREST_BOARD_ID:
            console.print("[red]Error:[/red] Pinterest credentials not configured. Run 'auth pinterest' first.")
            db.close()
            return
        publisher = PinterestPublisher(config.PINTEREST_ACCESS_TOKEN, config.PINTEREST_BOARD_ID)
    else:
        if not config.INSTAGRAM_ACCESS_TOKEN or not config.INSTAGRAM_USER_ID:
            console.print("[red]Error:[/red] Instagram credentials not configured. Run 'auth instagram' first.")
            db.close()
            return
        publisher = InstagramPublisher(config.INSTAGRAM_USER_ID, config.INSTAGRAM_ACCESS_TOKEN)

    if not publisher.validate_credentials():
        console.print(f"[red]Error:[/red] {platform} credentials are invalid or expired.")
        db.close()
        return

    console.print(f"Publishing {len(posts)} posts to {platform}...")

    success = 0
    for post in posts:
        try:
            platform_id = publisher.publish(post)
            db.mark_published(post.id, platform_id)
            console.print(f"  [green]✓[/green] Published: {post.caption[:50]}...")
            success += 1
        except Exception as e:
            db.mark_failed(post.id, str(e))
            console.print(f"  [red]✗[/red] Failed: {e}")

    publisher.close()
    db.close()
    console.print(f"\n[green]Done![/green] Published {success}/{len(posts)} posts.")


@cli.command()
def status():
    """Show queue statistics."""
    db = get_db()
    stats = db.get_stats()
    db.close()

    table = Table(title="Post Queue Status")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Total Listings Scraped", str(stats["total_listings"]))
    table.add_row("Draft Posts", str(stats.get("draft", 0)))
    table.add_row("Approved (ready to publish)", str(stats.get("approved", 0)))
    table.add_row("Published", str(stats.get("published", 0)))
    table.add_row("Failed", str(stats.get("failed", 0)))

    console.print(table)


@cli.group()
def auth():
    """Authenticate with social media platforms."""
    pass


@auth.command("pinterest")
def auth_pinterest():
    """Run Pinterest OAuth2 authorization flow."""
    if not config.PINTEREST_APP_ID or not config.PINTEREST_APP_SECRET:
        console.print("[red]Error:[/red] Set PINTEREST_APP_ID and PINTEREST_APP_SECRET in .env first.")
        console.print("Get these from https://developers.pinterest.com/apps/")
        return

    oauth = PinterestOAuth(config.PINTEREST_APP_ID, config.PINTEREST_APP_SECRET)

    try:
        tokens = oauth.authorize()
        console.print("\n[green]Authorization successful![/green]")
        console.print(f"\nAdd these to your .env file:")
        console.print(f"  PINTEREST_ACCESS_TOKEN={tokens.get('access_token', '')}")
        console.print(f"  PINTEREST_REFRESH_TOKEN={tokens.get('refresh_token', '')}")

        # Offer to list boards
        if Confirm.ask("\nWould you like to list your boards to get the BOARD_ID?"):
            publisher = PinterestPublisher(tokens["access_token"], "")
            boards = publisher.get_boards()
            publisher.close()

            table = Table(title="Your Pinterest Boards")
            table.add_column("Board ID", style="bold")
            table.add_column("Name")
            for board in boards:
                table.add_row(board["id"], board["name"])
            console.print(table)
            console.print("\nSet PINTEREST_BOARD_ID in .env to the board you want to post to.")

    except Exception as e:
        console.print(f"[red]Authorization failed:[/red] {e}")


@auth.command("instagram")
def auth_instagram():
    """Show instructions for Instagram Business account setup."""
    console.print("\n[bold]Instagram Business Account Setup[/bold]\n")
    console.print("1. Convert your Instagram account to a Business account:")
    console.print("   Settings > Account > Switch to Professional Account > Business")
    console.print("\n2. Create/connect a Facebook Page:")
    console.print("   Settings > Account > Linked Accounts > Facebook")
    console.print("\n3. Create a Meta Developer App:")
    console.print("   https://developers.facebook.com/apps/")
    console.print("   - Add 'Instagram Graph API' product")
    console.print("   - Add permissions: instagram_basic, instagram_content_publish")
    console.print("\n4. Generate a token via Graph API Explorer:")
    console.print("   https://developers.facebook.com/tools/explorer/")
    console.print("   - Select your app, get User Token with instagram permissions")
    console.print("\n5. Get your Instagram User ID:")
    console.print("   GET /me/accounts → page_id → GET /{page_id}?fields=instagram_business_account")
    console.print("\n6. Add to .env:")
    console.print("   INSTAGRAM_USER_ID=<your_ig_user_id>")
    console.print("   INSTAGRAM_ACCESS_TOKEN=<your_token>")
    console.print("\n[yellow]Note:[/yellow] For production use, submit your app for Meta App Review.")

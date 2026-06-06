"""Flask web UI for the Social Media Agent."""
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, render_template, request, jsonify, redirect, url_for, abort

import config
from queue.database import Database
from queue.models import Post, PostStatus, Platform
from scraper.depop_scraper import DepopScraper
from scraper.models import DepopListing
from captions.generator import CaptionGenerator
from publishers.pinterest import PinterestPublisher
from auth.pinterest_oauth import PinterestOAuth
import secrets

app = Flask(__name__)

# Track background task status
task_status = {"running": False, "message": "", "type": "", "progress": 0, "step": ""}

# Scheduler state
scheduler_state = {"enabled": False, "interval_hours": 6, "next_run": None, "timer": None}

# Settings file path
SETTINGS_PATH = Path(config.BASE_DIR) / "data" / "settings.json"


def get_db() -> Database:
    return Database(config.DATABASE_PATH)


def load_settings() -> dict:
    """Load user settings from JSON file."""
    defaults = {
        "shop_username": config.DEPOP_SHOP_USERNAME,
        "auto_post_enabled": False,
        "auto_post_interval_hours": 6,
        "auto_post_platform": "pinterest",
        "auto_approve": False,
        "use_ai_captions": True,
    }
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text())
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(settings: dict):
    """Persist settings to JSON file."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


def get_shop_username() -> str:
    settings = load_settings()
    return settings.get("shop_username") or config.DEPOP_SHOP_USERNAME


def get_pinterest_credentials() -> tuple[str, str, bool]:
    """Get Pinterest access token, board ID, and sandbox flag from settings or .env."""
    settings = load_settings()
    token = settings.get("pinterest_access_token") or config.PINTEREST_ACCESS_TOKEN
    board_id = settings.get("pinterest_board_id") or config.PINTEREST_BOARD_ID
    sandbox = settings.get("pinterest_sandbox", False)
    return token, board_id, sandbox


# --- Scheduler ---

def run_scheduled_pipeline():
    """Run the full scrape -> generate -> (auto-approve) -> publish pipeline."""
    settings = load_settings()
    platform = settings.get("auto_post_platform", "pinterest")
    use_ai = settings.get("use_ai_captions", True)
    auto_approve = settings.get("auto_approve", False)

    task_status["running"] = True
    task_status["type"] = "scheduler"
    task_status["message"] = "Scheduler: Scraping listings from Crosslist..."

    try:
        # Step 1: Scrape
        scraper = DepopScraper()
        listings = scraper.scrape_shop()
        scraper.close()

        db = get_db()
        new_count = 0
        for listing in listings:
            if db.save_listing(listing):
                new_count += 1

        # Step 2: Generate captions for new listings
        plat = Platform(platform)
        unprocessed = db.get_unprocessed_listings(plat)
        task_status["message"] = f"Scheduler: Generating captions for {len(unprocessed)} listings..."

        generator = None
        if use_ai and config.ANTHROPIC_API_KEY:
            generator = CaptionGenerator(config.ANTHROPIC_API_KEY)

        for listing in unprocessed:
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

        # Step 3: Auto-approve if enabled
        if auto_approve:
            drafts = db.get_posts(status=PostStatus.DRAFT, platform=plat)
            for post in drafts:
                db.approve_post(post.id)

        # Step 4: Publish approved posts
        approved_posts = db.get_posts(status=PostStatus.APPROVED, platform=plat)
        if approved_posts and plat == Platform.PINTEREST:
            token, board_id, sandbox = get_pinterest_credentials()
            if token and board_id:
                publisher = PinterestPublisher(token, board_id, sandbox=sandbox)
                success = 0
                for post in approved_posts:
                    try:
                        platform_id = publisher.publish(post)
                        db.mark_published(post.id, platform_id)
                        success += 1
                    except Exception as e:
                        db.mark_failed(post.id, str(e))
                publisher.close()
                task_status["message"] = f"Scheduler done! Scraped {new_count} new, published {success} posts."
            else:
                task_status["message"] = f"Scheduler: Scraped {new_count} new, generated {len(unprocessed)} captions. Pinterest not configured for auto-publish."
        else:
            task_status["message"] = f"Scheduler done! Scraped {new_count} new, generated {len(unprocessed)} drafts."

        db.close()
    except Exception as e:
        task_status["message"] = f"Scheduler error: {e}"
    finally:
        task_status["running"] = False
        schedule_next_run()


def schedule_next_run():
    """Schedule the next automatic run if enabled."""
    settings = load_settings()
    if not settings.get("auto_post_enabled"):
        scheduler_state["enabled"] = False
        scheduler_state["next_run"] = None
        return

    interval = settings.get("auto_post_interval_hours", 6)
    scheduler_state["enabled"] = True
    scheduler_state["interval_hours"] = interval

    # Cancel existing timer
    if scheduler_state["timer"]:
        scheduler_state["timer"].cancel()

    next_time = datetime.now().timestamp() + (interval * 3600)
    scheduler_state["next_run"] = datetime.fromtimestamp(next_time).strftime("%Y-%m-%d %H:%M")

    timer = threading.Timer(interval * 3600, run_scheduled_pipeline)
    timer.daemon = True
    timer.start()
    scheduler_state["timer"] = timer


# --- Routes ---

@app.route("/")
def dashboard():
    db = get_db()
    stats = db.get_stats()
    drafts = db.get_posts(status=PostStatus.DRAFT)
    approved = db.get_posts(status=PostStatus.APPROVED)
    published = db.get_posts(status=PostStatus.PUBLISHED, platform=None)

    for post_list in [drafts, approved, published]:
        for post in post_list:
            listing = db.get_listing(post.listing_id)
            post._listing_title = listing.title if listing else post.listing_id

    db.close()
    settings = load_settings()

    return render_template(
        "dashboard.html",
        stats=stats,
        drafts=drafts,
        approved=approved,
        published=published[-10:],
        task_status=task_status,
        shop_username=settings.get("shop_username", ""),
        has_pinterest=bool(get_pinterest_credentials()[0]),
        has_instagram=bool(config.INSTAGRAM_ACCESS_TOKEN),
        settings=settings,
        scheduler=scheduler_state,
    )


@app.route("/scrape", methods=["POST"])
def scrape():
    if task_status["running"]:
        return jsonify({"error": "A task is already running"}), 409

    def run_scrape():
        task_status["running"] = True
        task_status["type"] = "scrape"
        task_status["step"] = "Scraping Listings"
        task_status["progress"] = 10
        task_status["message"] = "Opening Crosslist and loading listings..."
        try:
            scraper = DepopScraper()
            task_status["progress"] = 30
            task_status["message"] = "Reading listings from Crosslist dashboard..."
            listings = scraper.scrape_shop()
            scraper.close()

            task_status["progress"] = 70
            task_status["message"] = f"Found {len(listings)} listings. Saving to database..."

            db = get_db()
            new_count = 0
            for i, listing in enumerate(listings):
                if db.save_listing(listing):
                    new_count += 1
                task_status["progress"] = 70 + int(30 * (i + 1) / max(len(listings), 1))
            db.close()
            task_status["progress"] = 100
            task_status["message"] = f"Done! Found {len(listings)} listings, {new_count} new."
        except Exception as e:
            task_status["message"] = f"Error: {e}"
        finally:
            task_status["running"] = False

    threading.Thread(target=run_scrape, daemon=True).start()
    return redirect(url_for("dashboard"))


@app.route("/generate", methods=["POST"])
def generate():
    platform = request.form.get("platform", "pinterest")
    settings = load_settings()
    use_ai = settings.get("use_ai_captions", True)

    if task_status["running"]:
        return jsonify({"error": "A task is already running"}), 409

    def run_generate():
        task_status["running"] = True
        task_status["type"] = "generate"
        task_status["step"] = "Generating Captions"
        task_status["progress"] = 5
        plat = Platform(platform)

        db = get_db()
        listings = db.get_unprocessed_listings(plat)
        task_status["message"] = f"Found {len(listings)} listings to generate {platform} captions for..."

        if not listings:
            task_status["progress"] = 100
            task_status["message"] = "No unprocessed listings. Scrape first."
            task_status["running"] = False
            db.close()
            return

        generator = None
        if use_ai and config.ANTHROPIC_API_KEY:
            generator = CaptionGenerator(config.ANTHROPIC_API_KEY)

        try:
            for i, listing in enumerate(listings):
                task_status["progress"] = 5 + int(95 * i / len(listings))
                task_status["message"] = f"Generating caption {i + 1}/{len(listings)}: {listing.title[:50]}..."

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

            task_status["progress"] = 100
            task_status["message"] = f"Done! Generated {len(listings)} draft posts."
        except Exception as e:
            task_status["message"] = f"Error: {e}"
        finally:
            db.close()
            task_status["running"] = False

    threading.Thread(target=run_generate, daemon=True).start()
    return redirect(url_for("dashboard"))


@app.route("/approve/<int:post_id>", methods=["POST"])
def approve(post_id: int):
    db = get_db()
    db.approve_post(post_id)
    db.close()
    return redirect(url_for("dashboard"))


@app.route("/reject/<int:post_id>", methods=["POST"])
def reject(post_id: int):
    db = get_db()
    db.reject_post(post_id)
    db.close()
    return redirect(url_for("dashboard"))


@app.route("/unapprove/<int:post_id>", methods=["POST"])
def unapprove(post_id: int):
    db = get_db()
    db.unapprove_post(post_id)
    db.close()
    return redirect(url_for("dashboard"))


@app.route("/clear-error/<int:post_id>", methods=["POST"])
def clear_error(post_id: int):
    db = get_db()
    db.clear_post_error(post_id)
    db.close()
    return redirect(url_for("dashboard"))


@app.route("/approve-all", methods=["POST"])
def approve_all():
    db = get_db()
    drafts = db.get_posts(status=PostStatus.DRAFT)
    for post in drafts:
        db.approve_post(post.id)
    db.close()
    return redirect(url_for("dashboard"))


@app.route("/edit/<int:post_id>", methods=["POST"])
def edit_caption(post_id: int):
    caption = request.form.get("caption", "")
    if caption:
        db = get_db()
        db.update_caption(post_id, caption)
        db.close()
    return redirect(url_for("dashboard"))


@app.route("/publish", methods=["POST"])
def publish():
    platform = request.form.get("platform", "pinterest")

    if task_status["running"]:
        return jsonify({"error": "A task is already running"}), 409

    def run_publish():
        task_status["running"] = True
        task_status["type"] = "publish"
        task_status["step"] = f"Publishing to {platform.title()}"
        task_status["progress"] = 5
        plat = Platform(platform)

        db = get_db()
        posts = db.get_posts(status=PostStatus.APPROVED, platform=plat)
        task_status["message"] = f"Found {len(posts)} approved posts to publish..."

        if not posts:
            task_status["progress"] = 100
            task_status["message"] = "No approved posts to publish."
            task_status["running"] = False
            db.close()
            return

        if plat == Platform.PINTEREST:
            token, board_id, sandbox = get_pinterest_credentials()
            if not token or not board_id:
                task_status["progress"] = 100
                task_status["message"] = "Pinterest not configured. Add your Access Token and Board ID in Settings."
                task_status["running"] = False
                db.close()
                return
            publisher = PinterestPublisher(token, board_id, sandbox=sandbox)
        else:
            task_status["progress"] = 100
            task_status["message"] = "Instagram publishing not yet configured."
            task_status["running"] = False
            db.close()
            return

        try:
            success = 0
            errors = []
            for i, post in enumerate(posts):
                task_status["progress"] = 5 + int(95 * i / len(posts))
                task_status["message"] = f"Publishing post {i + 1}/{len(posts)}: {post.caption[:50]}..."
                try:
                    platform_id = publisher.publish(post)
                    db.mark_published(post.id, platform_id)
                    success += 1
                except Exception as e:
                    error_msg = str(e)
                    db.mark_failed(post.id, error_msg)
                    errors.append(error_msg)

            task_status["progress"] = 100
            if success == len(posts):
                task_status["message"] = f"Done! Published {success}/{len(posts)} posts."
            elif errors:
                task_status["message"] = f"Done! Published {success}/{len(posts)} posts. Error: {errors[0][:150]}"
            publisher.close()
        except Exception as e:
            task_status["message"] = f"Error: {e}"
        finally:
            db.close()
            task_status["running"] = False

    threading.Thread(target=run_publish, daemon=True).start()
    return redirect(url_for("dashboard"))


@app.route("/settings", methods=["GET"])
def settings_page():
    settings = load_settings()
    return render_template("settings.html", settings=settings, scheduler=scheduler_state)


@app.route("/settings", methods=["POST"])
def save_settings_route():
    settings = {
        "shop_username": request.form.get("shop_username", "").strip(),
        "pinterest_app_id": request.form.get("pinterest_app_id", "").strip(),
        "pinterest_app_secret": request.form.get("pinterest_app_secret", "").strip(),
        "pinterest_access_token": request.form.get("pinterest_access_token", "").strip(),
        "pinterest_board_id": request.form.get("pinterest_board_id", "").strip(),
        "pinterest_sandbox": request.form.get("pinterest_sandbox") == "on",
        "auto_post_enabled": request.form.get("auto_post_enabled") == "on",
        "auto_post_interval_hours": int(request.form.get("auto_post_interval_hours", 6)),
        "auto_post_platform": request.form.get("auto_post_platform", "pinterest"),
        "auto_approve": request.form.get("auto_approve") == "on",
        "use_ai_captions": request.form.get("use_ai_captions") == "on",
    }
    save_settings(settings)

    # Update scheduler
    if settings["auto_post_enabled"]:
        schedule_next_run()
    else:
        if scheduler_state["timer"]:
            scheduler_state["timer"].cancel()
        scheduler_state["enabled"] = False
        scheduler_state["next_run"] = None

    return redirect(url_for("settings_page"))


@app.route("/pinterest-test", methods=["POST"])
def pinterest_test():
    """Test Pinterest credentials, list boards, and optionally create a sandbox board."""
    action = request.form.get("action", "test")
    token, board_id, sandbox = get_pinterest_credentials()

    if not token:
        return jsonify({"error": "No Pinterest access token configured. Add one in Settings."}), 400

    publisher = PinterestPublisher(token, board_id, sandbox=sandbox)

    if action == "test":
        # Test credentials
        result = publisher.validate_credentials()
        publisher.close()
        env = "SANDBOX" if sandbox else "PRODUCTION"
        result["message"] = f"[{env}] {result['message']}"
        return jsonify({"success": result["valid"], "message": result["message"]})

    elif action == "list_boards":
        try:
            boards = publisher.get_boards()
            publisher.close()
            return jsonify({"success": True, "boards": [{"id": b["id"], "name": b["name"]} for b in boards]})
        except Exception as e:
            publisher.close()
            return jsonify({"success": False, "message": str(e)})

    elif action == "create_board":
        board_name = request.form.get("board_name", "Social Media Agent Test")
        try:
            board = publisher.create_board(board_name, "Auto-created by Social Media Agent for testing")
            publisher.close()
            return jsonify({"success": True, "board_id": board["id"], "board_name": board["name"]})
        except Exception as e:
            publisher.close()
            return jsonify({"success": False, "message": str(e)})

    publisher.close()
    return jsonify({"error": "Unknown action"}), 400


# --- Pinterest OAuth Web Flow ---

@app.route("/auth/pinterest/start")
def pinterest_auth_start():
    """Start the Pinterest OAuth flow — redirects user to Pinterest to authorize."""
    settings = load_settings()
    app_id = settings.get("pinterest_app_id") or config.PINTEREST_APP_ID
    app_secret = settings.get("pinterest_app_secret") or config.PINTEREST_APP_SECRET

    if not app_id or not app_secret:
        task_status["message"] = "Set your Pinterest App ID and App Secret in Settings first."
        return redirect(url_for("settings_page"))

    # Build redirect URI from the current request's host
    redirect_uri = f"http://{request.host}/auth/pinterest/callback"
    oauth = PinterestOAuth(app_id, app_secret, redirect_uri=redirect_uri)
    state = secrets.token_urlsafe(16)

    # Save redirect_uri for the callback to use
    settings["_oauth_redirect_uri"] = redirect_uri

    # Save state for verification on callback
    settings["_oauth_state"] = state
    settings["_oauth_redirect_uri"] = redirect_uri
    save_settings(settings)

    auth_url = oauth.get_auth_url(state=state)
    return redirect(auth_url)


@app.route("/auth/pinterest/callback")
def pinterest_auth_callback():
    """Handle Pinterest OAuth callback — exchange code for tokens and save them."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        task_status["message"] = f"Pinterest authorization denied: {error}"
        return redirect(url_for("settings_page"))

    if not code:
        task_status["message"] = "Authorization failed: no code received from Pinterest."
        return redirect(url_for("settings_page"))

    settings = load_settings()

    # Verify state
    expected_state = settings.get("_oauth_state", "")
    if state != expected_state:
        task_status["message"] = "Authorization failed: state mismatch (possible CSRF attack)."
        return redirect(url_for("settings_page"))

    app_id = settings.get("pinterest_app_id") or config.PINTEREST_APP_ID
    app_secret = settings.get("pinterest_app_secret") or config.PINTEREST_APP_SECRET
    redirect_uri = settings.get("_oauth_redirect_uri", f"http://{request.host}/auth/pinterest/callback")

    oauth = PinterestOAuth(app_id, app_secret, redirect_uri=redirect_uri)

    try:
        tokens = oauth.exchange_code(code)
        # Save tokens to settings
        settings["pinterest_access_token"] = tokens.get("access_token", "")
        settings["pinterest_refresh_token"] = tokens.get("refresh_token", "")
        settings.pop("_oauth_state", None)
        save_settings(settings)

        task_status["message"] = "Pinterest connected successfully! Access token saved."
    except Exception as e:
        task_status["message"] = f"Failed to exchange Pinterest code for token: {e}"

    return redirect(url_for("settings_page"))


@app.route("/run-now", methods=["POST"])
def run_now():
    """Manually trigger the scheduler pipeline."""
    if task_status["running"]:
        return jsonify({"error": "A task is already running"}), 409

    threading.Thread(target=run_scheduled_pipeline, daemon=True).start()
    return redirect(url_for("dashboard"))


@app.route("/clear-status", methods=["POST"])
def clear_status():
    task_status["message"] = ""
    task_status["type"] = ""
    task_status["progress"] = 0
    task_status["step"] = ""
    return redirect(url_for("dashboard"))


@app.route("/reject-all-drafts", methods=["POST"])
def reject_all_drafts():
    if request.form.get("confirm_text", "").strip().lower() != "reject all drafts":
        task_status["message"] = "Confirmation text didn't match. No drafts were deleted."
        return redirect(url_for("settings_page"))
    db = get_db()
    db.reject_all_drafts()
    db.close()
    task_status["message"] = "All drafts rejected."
    return redirect(url_for("settings_page"))


@app.route("/clear-all-listings", methods=["POST"])
def clear_all_listings():
    if request.form.get("confirm_text", "").strip().lower() != "clear everything":
        task_status["message"] = "Confirmation text didn't match. Nothing was deleted."
        return redirect(url_for("settings_page"))
    db = get_db()
    db.clear_all_listings()
    db.close()
    task_status["message"] = "All listings and unpublished posts cleared."
    return redirect(url_for("settings_page"))


# --- Error Log ---

@app.route("/errors")
def error_log():
    db = get_db()
    errors = db.get_error_log()
    db.close()
    return render_template("errors.html", errors=errors)


# --- Compose (Multi-listing post editor) ---

@app.route("/compose")
def compose():
    db = get_db()
    listings = db.get_all_listings()
    db.close()
    return render_template("compose.html", listings=listings)


@app.route("/compose/generate-caption", methods=["POST"])
def compose_generate_caption():
    data = request.get_json()
    listing_ids = data.get("listing_ids", [])
    platform = data.get("platform", "pinterest")
    use_ai = data.get("use_ai", True)

    if not listing_ids:
        return jsonify({"error": "No listings selected"}), 400

    db = get_db()
    listings = db.get_listings_by_ids(listing_ids)
    db.close()

    if not listings:
        return jsonify({"error": "Listings not found"}), 404

    plat = Platform(platform)
    settings = load_settings()

    has_ai = use_ai and config.ANTHROPIC_API_KEY and settings.get("use_ai_captions", True)
    no_key_warning = ""

    if use_ai and not config.ANTHROPIC_API_KEY:
        no_key_warning = " (No API key set — used quick caption instead. Add ANTHROPIC_API_KEY to .env for AI captions.)"

    if len(listings) == 1:
        if has_ai:
            generator = CaptionGenerator(config.ANTHROPIC_API_KEY)
            caption = generator.generate(listings[0], plat)
        else:
            caption = CaptionGenerator("")._fallback_caption(listings[0], plat)
    else:
        if has_ai:
            generator = CaptionGenerator(config.ANTHROPIC_API_KEY)
            caption = generator.generate_multi(listings, plat)
        else:
            caption = CaptionGenerator("")._fallback_multi_caption(listings, plat)

    return jsonify({"caption": caption, "warning": no_key_warning})


@app.route("/compose/save", methods=["POST"])
def compose_save():
    data = request.get_json()
    listing_ids = data.get("listing_ids", [])
    platform = data.get("platform", "pinterest")
    caption = data.get("caption", "").strip()
    status = data.get("status", "draft")

    if not listing_ids or not caption:
        return jsonify({"error": "Missing required fields"}), 400

    db = get_db()
    listings = db.get_listings_by_ids(listing_ids)

    if not listings:
        db.close()
        return jsonify({"error": "Listings not found"}), 404

    # Collect all images from selected listings
    all_images = []
    for listing in listings:
        all_images.extend(listing.images)

    # Use first listing's URL as destination, or empty
    destination = listings[0].url if listings[0].url else ""

    # Store all listing IDs joined with comma for the listing_id field
    combined_listing_id = ",".join(listing_ids)

    plat = Platform(platform)
    post_status = PostStatus.APPROVED if status == "approved" else PostStatus.DRAFT

    post = Post(
        listing_id=combined_listing_id,
        platform=plat,
        status=post_status,
        caption=caption,
        image_urls=all_images,
        destination_url=destination,
    )
    db.add_post(post)
    db.close()

    return jsonify({"success": True})


# Initialize scheduler on startup
def init_scheduler():
    settings = load_settings()
    if settings.get("auto_post_enabled"):
        schedule_next_run()


init_scheduler()


if __name__ == "__main__":
    print("Starting Social Media Agent on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)

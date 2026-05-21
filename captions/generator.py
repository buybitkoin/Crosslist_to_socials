import anthropic

from scraper.models import DepopListing
from captions.prompts import (
    PINTEREST_PROMPT, INSTAGRAM_PROMPT,
    PINTEREST_MULTI_PROMPT, INSTAGRAM_MULTI_PROMPT,
)
from queue.models import Platform


class CaptionGenerator:
    PROMPTS = {
        Platform.PINTEREST: PINTEREST_PROMPT,
        Platform.INSTAGRAM: INSTAGRAM_PROMPT,
    }
    MULTI_PROMPTS = {
        Platform.PINTEREST: PINTEREST_MULTI_PROMPT,
        Platform.INSTAGRAM: INSTAGRAM_MULTI_PROMPT,
    }

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def generate(self, listing: DepopListing, platform: Platform) -> str:
        """Generate a platform-specific caption. Falls back to listing text on error."""
        try:
            return self._call_api(listing, platform)
        except Exception:
            return self._fallback_caption(listing, platform)

    def _call_api(self, listing: DepopListing, platform: Platform) -> str:
        prompt_template = self.PROMPTS[platform]
        prompt = prompt_template.format(
            title=listing.title,
            description=listing.description,
            price=listing.price,
            currency=listing.currency,
            brand=listing.brand or "Unknown",
            size=listing.size or "Not specified",
            condition=listing.condition or "Not specified",
        )

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def generate_multi(self, listings: list[DepopListing], platform: Platform) -> str:
        """Generate a caption for a multi-listing post."""
        try:
            return self._call_multi_api(listings, platform)
        except Exception:
            return self._fallback_multi_caption(listings, platform)

    def _call_multi_api(self, listings: list[DepopListing], platform: Platform) -> str:
        items_block = ""
        for i, listing in enumerate(listings, 1):
            items_block += f"\nItem {i}:\n"
            items_block += f"  - Title: {listing.title}\n"
            items_block += f"  - Price: {listing.price} {listing.currency}\n"
            items_block += f"  - Brand: {listing.brand or 'Unknown'}\n"
            items_block += f"  - Size: {listing.size or 'Not specified'}\n"

        prompt = self.MULTI_PROMPTS[platform].format(items_block=items_block)

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    def _fallback_multi_caption(self, listings: list[DepopListing], platform: Platform) -> str:
        """Fallback for multi-listing posts when API is unavailable."""
        if platform == Platform.PINTEREST:
            titles = [l.title[:40] for l in listings]
            return f"Shop the look: {' + '.join(titles)} | Starting at ${min(l.price for l in listings):.0f} | Tap to shop all pieces!"

        caption = "✨ New curated set just dropped!\n\n"
        for listing in listings:
            caption += f"• {listing.title[:40]} — ${listing.price:.0f}\n"
        caption += "\nLink in bio to shop! 🛍️\n\n"
        caption += "#depop #thrifted #vintagefashion #sustainablestyle #shoptheoutfit"
        return caption

    def _fallback_caption(self, listing: DepopListing, platform: Platform) -> str:
        """Use listing text directly when API is unavailable."""
        if platform == Platform.PINTEREST:
            parts = [listing.title]
            if listing.brand:
                parts.append(f"Brand: {listing.brand}")
            if listing.size:
                parts.append(f"Size: {listing.size}")
            parts.append(f"${listing.price:.0f}")
            parts.append("Shop now on Depop!")
            return " | ".join(parts)

        # Instagram
        caption = f"✨ {listing.title}\n\n"
        if listing.brand:
            caption += f"Brand: {listing.brand} | "
        if listing.size:
            caption += f"Size: {listing.size} | "
        caption += f"${listing.price:.0f}\n\n"
        caption += "Link in bio to shop! 🛍️\n\n"
        caption += "#depop #thrifted #vintagefashion #sustainablestyle #reseller"
        return caption

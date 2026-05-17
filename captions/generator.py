import anthropic

from scraper.models import DepopListing
from captions.prompts import PINTEREST_PROMPT, INSTAGRAM_PROMPT
from queue.models import Platform


class CaptionGenerator:
    PROMPTS = {
        Platform.PINTEREST: PINTEREST_PROMPT,
        Platform.INSTAGRAM: INSTAGRAM_PROMPT,
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

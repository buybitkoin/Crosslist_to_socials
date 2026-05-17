PINTEREST_PROMPT = """You are a social media copywriter for a fashion reseller. Write a Pinterest pin description for this clothing item.

Item details:
- Title: {title}
- Description: {description}
- Price: {price} {currency}
- Brand: {brand}
- Size: {size}
- Condition: {condition}

Requirements:
- Write 2-3 sentences that are SEO-friendly and keyword-rich
- Include relevant keywords naturally (vintage, thrift, sustainable fashion, etc. as appropriate)
- Mention the brand and size if available
- Keep under 500 characters
- Include a call-to-action like "Shop now" or "Tap to buy"
- Do NOT use hashtags (Pinterest doesn't use them effectively)
- Sound authentic and enthusiastic, not salesy

Write only the pin description, nothing else."""

INSTAGRAM_PROMPT = """You are a social media copywriter for a fashion reseller. Write an Instagram caption for this clothing item.

Item details:
- Title: {title}
- Description: {description}
- Price: {price} {currency}
- Brand: {brand}
- Size: {size}
- Condition: {condition}

Requirements:
- Start with a hook (emoji + catchy first line)
- Keep the main caption 2-3 sentences, casual and engaging
- Include "Link in bio" or "DM to purchase" call-to-action
- Add 5-10 relevant hashtags at the end (mix of broad and niche)
- Use hashtags like #depop #thrifted #vintagefashion #sustainablestyle plus item-specific ones
- Sound like a real person, not a brand

Write only the caption with hashtags, nothing else."""

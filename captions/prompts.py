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

PINTEREST_MULTI_PROMPT = """You are a social media copywriter for a fashion reseller. Write a Pinterest pin description for a "Shop the Look" style post featuring multiple clothing items together.

Items in this post:
{items_block}

Requirements:
- Write 2-4 sentences that tie the items together as a cohesive look or collection
- Be SEO-friendly and keyword-rich (vintage, thrift, sustainable fashion, etc. as appropriate)
- Mention brands and key details naturally
- Keep under 500 characters
- Include a call-to-action like "Shop the full look" or "Tap to see all pieces"
- Do NOT use hashtags
- Sound authentic and enthusiastic, not salesy

Write only the pin description, nothing else."""

INSTAGRAM_MULTI_PROMPT = """You are a social media copywriter for a fashion reseller. Write an Instagram caption for a post featuring multiple clothing items together as a look or collection.

Items in this post:
{items_block}

Requirements:
- Start with a hook (emoji + catchy first line about the collection/look)
- Keep the main caption 2-4 sentences, casual and engaging
- Briefly reference the items as a styled look or curated set
- Include "Link in bio" or "DM to purchase" call-to-action
- Add 5-10 relevant hashtags at the end
- Sound like a real person, not a brand

Write only the caption with hashtags, nothing else."""

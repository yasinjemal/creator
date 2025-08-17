from typing import Dict, Any
from ai_client import AIClient

ai = AIClient()

PLATFORM_PROMPTS = {
    "instagram": "Write an Instagram caption in {tone} voice, max 2200 characters. Include relevant hashtags.",
    "twitter": "Write a tweet in {tone} voice, max 280 characters. Include 3-5 hashtags.",
    "youtube": "Write a YouTube video description and 3-line short caption in {tone} voice.",
    "tiktok": "Write a TikTok caption in {tone} voice with trending hashtag suggestions.",
    "linkedin": "Write a professional LinkedIn post in {tone} voice, suitable for company page.",
}


def generate_content(brand: Dict[str, Any], platform: str, prompt_overrides: Dict[str, Any] = None) -> Dict[str, Any]:
    tone = brand.get("voice", {}).get("tone", "neutral")
    tpl = PLATFORM_PROMPTS.get(platform, PLATFORM_PROMPTS["instagram"])
    prompt = tpl.format(tone=tone)
    if prompt_overrides:
        prompt += "\n" + prompt_overrides.get("extra", "")

    text = ai.generate(prompt)

    # simple hashtag extraction stub
    hashtags = ["#example"]

    return {
        "platform": platform,
        "caption": text,
        "hashtags": hashtags,
        "brand_id": str(brand.get("_id"))
    }

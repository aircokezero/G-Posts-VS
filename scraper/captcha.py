"""
CAPTCHA/verification detection — checks several signals rather than one
brittle selector, since exact CAPTCHA markup varies.
"""

def looks_like_captcha_or_block(driver) -> bool:
    page_source = driver.page_source.lower()
    url = driver.current_url.lower()

    signals = [
        "captcha" in page_source,
        "unusual traffic" in page_source,
        "recaptcha" in page_source,
        "/sorry/" in url,
        "verify you're human" in page_source,
    ]
    return any(signals)
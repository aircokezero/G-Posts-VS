"""
Selenium driver setup. Runs non-headless deliberately — a visible window
is what makes the CAPTCHA pause/resume flow possible (you solve it manually
in the actual browser window, the scraper waits and resumes).
"""

import undetected_chromedriver as uc


def get_driver():
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options)
    return driver
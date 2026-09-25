from scraper.config import get_driver
import time

driver = get_driver()
driver.get("https://maps.app.goo.gl/5G6T2J4Ho9LMLTP37")
time.sleep(5)
input("Look at the browser window. Press Enter here when you're ready to continue...")
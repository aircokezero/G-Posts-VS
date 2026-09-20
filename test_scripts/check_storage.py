from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

with open("test.jpg", "rb") as f:
    client.storage.from_(os.environ["SUPABASE_BUCKET"]).upload("test.jpg", f, {"content-type": "image/jpg"})

url = client.storage.from_(os.environ["SUPABASE_BUCKET"]).get_public_url("test.jpg")
print(url)
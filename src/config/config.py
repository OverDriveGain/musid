import os
from dotenv import load_dotenv

load_dotenv()

config = {
    "port": int(os.getenv("PORT", 3001)),
}

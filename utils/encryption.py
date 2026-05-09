from cryptography.fernet import Fernet
from config import ENCRYPTION_KEY

print("DEBUG KEY:", ENCRYPTION_KEY)

from cryptography.fernet import Fernet
cipher = Fernet(ENCRYPTION_KEY.encode())
import base64

# Initialize Fernet with the key from config
cipher = Fernet(ENCRYPTION_KEY.encode())

def encrypt_session(session_string: str) -> str:
    """Encrypt Pyrogram session string before saving to DB"""
    encrypted = cipher.encrypt(session_string.encode())
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_session(encrypted_data: str) -> str:
    """Decrypt session string when we need to use it"""
    try:
        decoded = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted = cipher.decrypt(decoded)
        return decrypted.decode()
    except Exception as e:
        from utils.logger import logger
        logger.error(f"Decryption failed: {e}")
        raise

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    logger.warning("cryptography package is not installed. DataEncryptor will raise errors when used.")

class DataEncryptor:
    """Fernet-based data-at-rest encryption for sensitive files."""
    
    def __init__(self, key_path: Optional[str] = None, key_file: Optional[str] = None):
        """Initialize the DataEncryptor.
        
        Args:
            key_path: Path to the encryption key file.
            key_file: Alias for key_path.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("The 'cryptography' package is required for DataEncryptor. Run 'pip install cryptography'.")
            
        if key_file is not None:
            self.key_path = key_file
        elif key_path is not None:
            self.key_path = key_path
        else:
            self.key_path = "./data/memory/encryption.key"
            
        os.makedirs(os.path.dirname(os.path.abspath(self.key_path)), exist_ok=True)
        
        try:
            self.key = self.load_key()
            self.cipher = Fernet(self.key)
            logger.info("DataEncryptor initialized with existing key.")
        except FileNotFoundError:
            self.key = self.generate_key()
            self.cipher = Fernet(self.key)
            logger.info("DataEncryptor initialized with new key.")
    
    def generate_key(self) -> bytes:
        """Generate a new Fernet key and save it to key_path.
        
        Returns:
            The generated key bytes.
        """
        key = Fernet.generate_key()
        with open(self.key_path, 'wb') as key_file:
            key_file.write(key)
        return key
    
    def load_key(self) -> bytes:
        """Load the Fernet key from the key_path.
        
        Returns:
            The key bytes.
        
        Raises:
            FileNotFoundError: If the key file doesn't exist.
        """
        if not os.path.exists(self.key_path):
            raise FileNotFoundError(f"Encryption key not found at {self.key_path}")
            
        with open(self.key_path, 'rb') as key_file:
            return key_file.read()
    
    def encrypt(self, data: str) -> bytes:
        """Encrypt a string.
        
        Args:
            data: The string to encrypt.
            
        Returns:
            The encrypted bytes.
        """
        return self.cipher.encrypt(data.encode('utf-8'))
    
    def decrypt(self, encrypted: bytes) -> str:
        """Decrypt encrypted bytes.
        
        Args:
            encrypted: The encrypted bytes.
            
        Returns:
            The decrypted string.
        """
        try:
            return self.cipher.decrypt(encrypted).decode('utf-8')
        except InvalidToken as e:
            logger.error("Failed to decrypt data: Invalid token.")
            raise ValueError("Invalid decryption token or corrupted data.") from e
    
    def encrypt_file(self, file_path: str) -> str:
        """Encrypt a file in place.
        
        Args:
            file_path: Path to the file to encrypt.
            
        Returns:
            The path to the encrypted file (same as file_path).
        """
        with open(file_path, 'rb') as f:
            data = f.read()
            
        encrypted_data = self.cipher.encrypt(data)
        
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)
            
        logger.info(f"Encrypted file: {file_path}")
        return file_path
    
    def decrypt_file(self, encrypted_path: str) -> str:
        """Read and decrypt a file.
        
        Args:
            encrypted_path: Path to the encrypted file.
            
        Returns:
            The decrypted file contents as a string.
        """
        with open(encrypted_path, 'rb') as f:
            encrypted_data = f.read()
            
        decrypted_bytes = self.cipher.decrypt(encrypted_data)
        return decrypted_bytes.decode('utf-8')

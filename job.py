import struct
import binascii
from typing import Optional

class Job:
    def __init__(self, nicehash=False):
        self.blob = None
        self.seed_hash = None
        self.target = None
        self.id = None
        self.height = 0
        self.diff = 0
        self.size = 0
        self.nicehash = nicehash
        self.algo: Optional[str] = None
        self.nonce_size = 4  # Default nonce size for Monero
        self.nonce_offset = 39  # Default nonce offset for Monero

    def set_blob(self, blob: str) -> bool:
        """Parse and validate job blob"""
        if not blob:
            return False
            
        try:
            # Convert hex string to bytes
            blob_bytes = binascii.unhexlify(blob)
            if not blob_bytes:
                return False
                
            self.blob = blob
            self.size = len(blob_bytes)
            return True
        except:
            return False

    def set_target(self, target: str) -> bool:
        """Parse and validate target difficulty"""
        if not target:
            return False
            
        try:
            # Convert hex target to numeric difficulty
            target_hex = target
            if len(target_hex) <= 8:
                # Target is already in compact format
                target_num = struct.unpack("<I", binascii.unhexlify(target_hex.zfill(8)))[0]
                self.target = target_num
                self.diff = self._target_to_diff(target_num)
            else:
                # Target is in full 256-bit format
                target_bytes = binascii.unhexlify(target_hex)
                if len(target_bytes) == 32:
                    self.target = int.from_bytes(target_bytes, 'little')
                    self.diff = self._target_to_diff(self.target)
                else:
                    return False
            return True
        except:
            return False
            
    def set_id(self, job_id: str) -> bool:
        """Set and validate job ID"""
        if not job_id:
            return False
        self.id = job_id
        return True

    def set_height(self, height: int) -> None:
        """Set block height"""
        self.height = height

    def set_seed_hash(self, seed_hash: str) -> bool:
        """Set RandomX seed hash"""
        if not seed_hash or len(seed_hash) != 64:
            return False
        self.seed_hash = seed_hash
        return True

    def set_algo(self, algo: str) -> None:
        """Set the algorithm and adjust nonce params"""
        self.algo = algo
        if algo == 'kawpow':
            self.nonce_offset = -8  # Nonce is at the end of the header
            self.nonce_size = 8
        else: # Default to RandomX
            self.nonce_offset = 39
            self.nonce_size = 4

    def _target_to_diff(self, target: int) -> int:
        """Convert mining target to difficulty"""
        # 0xFFFFFFFFFFFFFFFF / target = difficulty
        if target == 0:
            return 0
        return int(0xFFFFFFFFFFFFFFFF / target)

    def get_nonce_offset(self) -> int:
        """Get the offset of the nonce in the blob"""
        return self.nonce_offset

    def get_nonce_size(self) -> int:
        """Get the size of the nonce field"""
        return self.nonce_size
        
    def is_valid(self) -> bool:
        """Check if job has all required fields"""
        return (self.blob is not None and 
                self.target is not None and 
                self.id is not None)

    def __eq__(self, other) -> bool:
        """Compare jobs for equality"""
        if not isinstance(other, Job):
            return False
        return (self.blob == other.blob and
                self.target == other.target and
                self.id == other.id and
                self.height == other.height and
                self.seed_hash == other.seed_hash)
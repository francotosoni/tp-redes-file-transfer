from lib.constants import BLOCK_SIZE
import hashlib


def hashing(file_path):
    file_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        fb = f.read(BLOCK_SIZE)
        while len(fb) > 0:
            file_hash.update(fb)
            fb = f.read(BLOCK_SIZE)
    return file_hash.digest()

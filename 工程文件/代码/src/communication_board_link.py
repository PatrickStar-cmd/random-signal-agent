"""RS1 UART data frames shared by the desktop reference and board projects."""
from struct import Struct

import numpy as np

from src.communication_codecs import crc

HEADER = Struct('>3sHH')
MAGIC = b'RS\x01'


def crc16_bytes(data):
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    return np.packbits(crc(bits, 16)).tobytes()


def encode_frame(bits, sequence):
    body = HEADER.pack(MAGIC, sequence, len(bits)) + np.packbits(bits, bitorder='big').tobytes()
    return body + crc16_bytes(body)


def decode_frame(frame, sequence):
    if len(frame) < HEADER.size + 2:
        raise ValueError('UART 帧头不完整。')
    magic, seq, count = HEADER.unpack_from(frame)
    if magic != MAGIC or len(frame) != HEADER.size + (count + 7) // 8 + 2:
        raise ValueError('UART 帧格式或长度异常。')
    if crc16_bytes(frame[:-2]) != frame[-2:]:
        raise ValueError('UART 帧 CRC 校验失败。')
    if seq != sequence:
        raise ValueError('UART 帧序号不匹配。')
    return np.unpackbits(np.frombuffer(frame[HEADER.size:-2], dtype=np.uint8), count=count, bitorder='big')

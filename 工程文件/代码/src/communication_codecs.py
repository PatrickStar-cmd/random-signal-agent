"""Bit and source codecs for the communication lab (NumPy only).

LLRs use log(P(bit=0)/P(bit=1)). CRC polynomials are MSB-first,
CRC-16/CCITT-FALSE and CRC-32/MPEG-2 (no reflection or final XOR).
The LDPC code is an explicitly defined educational (128,64) IRA code.
"""
from functools import lru_cache
import numpy as np

SOURCE_CODECS = {'compand_encode', 'dpcm_encode', 'delta_encode'}
PAIRS = {'crc_check': 'crc_append', 'descramble': 'scramble',
         'conv_soft_decode': 'conv_encode', 'ldpc_decode': 'ldpc_encode',
         'compand_decode': 'compand_encode', 'dpcm_decode': 'dpcm_encode',
         'delta_decode': 'delta_encode'}


def pn(count, degree=7, seed=1):
    if degree not in (7, 9, 15) or not 0 < seed < 2 ** degree:
        raise ValueError('LFSR 初态须为 1 至 2ⁿ−1，阶数为 7、9 或 15。')
    tap = 4 if degree == 9 else 1
    result = np.empty(count, dtype=np.uint8)
    for i in range(count):
        result[i] = seed & 1
        feedback = (seed ^ (seed >> tap)) & 1
        seed = (seed >> 1) | (feedback << (degree - 1))
    return result


def crc(bits, width):
    polynomial = {16: 0x1021, 32: 0x04C11DB7}[width]
    register = (1 << width) - 1
    for bit in bits:
        feedback = ((register >> (width - 1)) & 1) ^ int(bit)
        register = (register << 1) & ((1 << width) - 1)
        if feedback:
            register ^= polynomial
    return np.array([(register >> i) & 1 for i in range(width - 1, -1, -1)], dtype=np.uint8)


def words_to_bits(values, width):
    return ((np.asarray(values, dtype=np.int64)[:, None] >> np.arange(width - 1, -1, -1)) & 1).astype(np.uint8).ravel()


def bits_to_words(bits, width):
    return np.asarray(bits).reshape(-1, width).dot(2 ** np.arange(width - 1, -1, -1))


def compand(x, law, inverse=False):
    """Continuous A=87.6 / mu=255 companding, followed by uniform quantization."""
    x = np.asarray(x); a = np.abs(x)
    if law == 0:
        y = np.expm1(a * np.log1p(255)) / 255 if inverse else np.log1p(255 * a) / np.log1p(255)
    else:
        constant = 1 + np.log(87.6)
        if inverse:
            y = np.where(a < 1 / constant, a * constant / 87.6, np.exp(a * constant - 1) / 87.6)
        else:
            y = np.where(a < 1 / 87.6, 87.6 * a / constant, (1 + np.log(np.maximum(87.6 * a, 1e-30))) / constant)
    return np.sign(x) * y


@lru_cache(maxsize=1)
def ldpc_matrix():
    """H=[A B], A columns have weight 3, B is lower bidiagonal.

    A[j,j]=A[(j+1)%64,j]=A[(j+9)%64,j]=1. Distinct differences
    avoid four-cycles inside A. B makes parity generation an accumulator.
    """
    h = np.zeros((64, 128), dtype=np.uint8)
    for j in range(64):
        h[[j, (j + 1) % 64, (j + 9) % 64], j] = 1
        h[j, 64 + j] = 1
        if j:
            h[j, 63 + j] = 1
    h.flags.writeable = False
    return h


def ldpc_encode(bits):
    data = np.pad(bits, (0, -len(bits) % 64)).reshape(-1, 64)
    rhs = (data @ ldpc_matrix()[:, :64].T) % 2
    parity = np.bitwise_xor.accumulate(rhs, axis=1)
    return np.concatenate((data, parity), axis=1).ravel().astype(np.uint8)


def ldpc_decode(llr, iterations=30, scale=.8):
    """Flooding normalized min-sum with syndrome termination, batched frames."""
    channel = np.clip(np.asarray(llr, dtype=float).reshape(-1, 128), -60, 60)
    h = ldpc_matrix(); rows, cols = np.nonzero(h)
    outgoing = channel[:, cols].copy(); incoming = np.zeros_like(outgoing)
    posterior = channel.copy(); used = 0
    for used in range(1, iterations + 1):
        for row in range(64):
            edges = np.flatnonzero(rows == row); values = outgoing[:, edges]
            signs = np.where(values < 0, -1., 1.); magnitudes = abs(values)
            minimum_index = np.argmin(magnitudes, axis=1)
            minima = np.partition(magnitudes, 1, axis=1)[:, :2]
            other_min = np.repeat(minima[:, :1], len(edges), axis=1)
            other_min[np.arange(len(channel)), minimum_index] = minima[:, 1]
            incoming[:, edges] = scale * np.prod(signs, axis=1)[:, None] * signs * other_min
        posterior = channel.copy()
        for edge, col in enumerate(cols):
            posterior[:, col] += incoming[:, edge]
        hard = (posterior < 0).astype(np.uint8)
        syndrome = (hard @ h.T) % 2
        if not np.any(syndrome):
            break
        outgoing = np.clip(posterior[:, cols] - incoming, -60, 60)
    return hard[:, :64].ravel(), {'iterations': used, 'failed_codewords': int(np.count_nonzero(np.any(syndrome, axis=1)))}


def soft_viterbi(llr):
    from src.communications import transition
    pairs = np.asarray(llr).reshape(-1, 2)
    scores = np.array([0., np.inf, np.inf, np.inf]); paths = np.zeros((len(pairs), 4), dtype=np.uint8)
    for i, pair in enumerate(pairs):
        updated = np.full(4, np.inf)
        for previous in range(4):
            for bit in (0, 1):
                dest, expected = transition(previous, bit)
                # Negative log likelihood up to a branch-independent constant.
                cost = scores[previous] + np.dot(expected, pair)
                if cost < updated[dest]:
                    updated[dest] = cost; paths[i, dest] = previous
        scores = updated - np.min(updated)
    bits = np.zeros(len(pairs), dtype=np.uint8); state = 0
    for i in range(len(pairs) - 1, -1, -1):
        bits[i] = state >> 1; state = int(paths[i, state])
    return bits[:-2]


def encoded_count(kind, count, q):
    if kind == 'crc_append': return count + q['width']
    if kind == 'ldpc_encode': return ((count + 63) // 64) * 128
    if kind in ('compand_encode', 'dpcm_encode'): return count * q['bits']
    return count


def encode(kind, data, q):
    if kind == 'crc_append': return np.r_[data, crc(data, q['width'])]
    if kind == 'scramble': return data ^ pn(len(data), q['degree'], q['initial'])
    if kind == 'ldpc_encode': return ldpc_encode(data)
    if kind == 'compand_encode':
        y = compand(np.clip(data / q['full_scale'], -1, 1), q['law'])
        return words_to_bits(np.rint((y + 1) / 2 * (2 ** q['bits'] - 1)), q['bits'])
    if kind == 'dpcm_encode':
        output = []; previous = 0.; levels = 2 ** q['bits'] - 1
        for sample in data:
            error = sample - q['predictor'] * previous
            value = int(np.rint((np.clip(error / q['full_scale'], -1, 1) + 1) / 2 * levels))
            previous = q['predictor'] * previous + (2 * value / levels - 1) * q['full_scale']
            output.append(value)
        return words_to_bits(output, q['bits'])
    if kind == 'delta_encode':
        output = []; previous = 0.
        for sample in data:
            bit = int(sample >= previous); previous += (2 * bit - 1) * q['step']; output.append(bit)
        return np.array(output, dtype=np.uint8)
    raise ValueError('未知扩展编码器。')


def decode(kind, data, q):
    info = {}
    if kind == 'crc_check':
        width = q['width']; info = {'crc_pass': bool(np.array_equal(data[-width:], crc(data[:-width], width))), 'crc_width': width}
        data = data[:-width]
    elif kind == 'descramble': data = data ^ pn(len(data), q['degree'], q['initial'])
    elif kind == 'conv_soft_decode': data = soft_viterbi(data)
    elif kind == 'ldpc_decode': data, info = ldpc_decode(data, q['iterations'], q['scale'])
    elif kind == 'compand_decode':
        y = 2 * bits_to_words(data, q['bits']) / (2 ** q['bits'] - 1) - 1
        data = compand(y, q['law'], True) * q['full_scale']
    elif kind == 'dpcm_decode':
        residual = (2 * bits_to_words(data, q['bits']) / (2 ** q['bits'] - 1) - 1) * q['full_scale']
        output = []; previous = 0.
        for error in residual:
            previous = q['predictor'] * previous + error; output.append(previous)
        data = np.array(output)
    elif kind == 'delta_decode': data = np.cumsum((2 * data.astype(float) - 1) * q['step'])
    else: raise ValueError('未知扩展译码器。')
    return data, info

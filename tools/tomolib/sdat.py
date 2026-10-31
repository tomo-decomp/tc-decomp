"""Sound archive (SDAT) extraction.

The cartridge carries one `sound_data.sdat` (about 24 MiB) holding every sound
the game plays, including the Mii voices.  An SDAT is four blocks:

    SYMB  names for the entries of each kind (sequences, banks, wave archives)
    INFO  offsets/sizes of each kind's records, inside the corresponding file
    FAT   (offset, size) of each archived file inside the FILE block
    FILE  the archived files themselves: SWAV samples, SWAR wave archives,
          SBNK banks and SSEQ sequences

Extraction turns each sample into a WAV file (PCM8, PCM16 and IMA-ADPCM all
occur) and each sequence into its raw byte stream, which is what an editor
such as a MIDI converter or the game's own tools expect.
"""

from __future__ import annotations

import struct
import wave

MAGIC = b"SDAT"

# Kinds, in the order the SDAT blocks list them.
KINDS = ("seq", "bank", "wavearc", "player", "group", "stream")

WAVE_FORMAT_PCM = 0x0001


class SdatError(ValueError):
    """The archive is malformed."""


def is_sdat(data: bytes) -> bool:
    return data[:4] == MAGIC


class Sdat:
    def __init__(self, data: bytes):
        if not is_sdat(data) or len(data) < 0x40:
            raise SdatError("not an SDAT")
        self.data = data
        self.header_size = struct.unpack_from("<H", data, 0x0C)[0]
        blocks = struct.unpack_from("<H", data, 0x0E)[0]
        self.blocks: dict[str, tuple[int, int]] = {}
        for i, name in enumerate(("symb", "info", "fat", "file")):
            if i >= blocks:
                break
            off, size = struct.unpack_from("<II", data, 0x10 + i * 8)
            self.blocks[name] = (off, size)

    # ------------------------------------------------------------ names
    def names(self) -> dict[str, list[str]]:
        """Symbol names per kind, from the SYMB block."""
        out: dict[str, list[str]] = {kind: [] for kind in KINDS}
        if "symb" not in self.blocks:
            return out
        base, size = self.blocks["symb"]
        end = base + size
        if self.data[base:base + 4] != b"SYMB":
            return out
        for i, kind in enumerate(KINDS):
            entry = base + 8 + i * 12
            if entry + 12 > end:
                break
            # The symbol table entry is (offset, size, data); the third word is
            # where this kind's names actually live.  The names are a run of
            # NUL-terminated strings, so split the rest of the block.
            name_offset = struct.unpack_from("<I", self.data, entry + 8)[0]
            if name_offset == 0:
                continue
            blob = self.data[base + name_offset:end]
            for raw in blob.split(b"\x00")[1:]:
                if not raw or not raw[:1].isalnum() and not raw[:1].isalpha():
                    if not raw:
                        continue
                try:
                    name = raw.decode("shift-jis")
                except UnicodeDecodeError:
                    break
                if not name or not all(ch.isprintable() for ch in name):
                    break
                out[kind].append(name)
                if len(out[kind]) > 4096:
                    break
        return out

    # ------------------------------------------------------------ files
    def files(self) -> list[tuple[int, bytes]]:
        """Every archived file as (id, payload), in FAT order."""
        fat_base, fat_size = self.blocks["fat"]
        file_base, file_size = self.blocks["file"]
        if self.data[fat_base:fat_base + 4] != b"FAT ":
            raise SdatError("missing FAT block")
        count = struct.unpack_from("<I", self.data, fat_base + 8)[0]
        records = fat_base + 0x0C
        out: list[tuple[int, bytes]] = []
        for i in range(count):
            off, size = struct.unpack_from("<II", self.data, records + i * 16)
            # FAT offsets are absolute within the SDAT.
            if off + size > len(self.data):
                raise SdatError(f"FAT entry {i} runs past the end")
            out.append((i, self.data[off:off + size]))
        del file_base, file_size
        return out

    def wave_archives(self) -> list[tuple[int, bytes]]:
        """SWAR payloads listed in the INFO block."""
        return [data for _, data in self.files() if data[:4] == b"SWAR"]


# ------------------------------------------------------------------ samples


SWAR_RECORD_SIZE = 12


def split_swar(data: bytes) -> list[bytes]:
    """Splits a SWAR into standalone SWAV files, one per sample.

    A SWAR is a DATA chunk whose payload starts with `count` 12-byte info
    records (codec, loop flag, rate, time, loop offset, non-loop length),
    then `count` u32 offsets into the sample data:

        0x00 u8   codec (0 = PCM8, 1 = PCM16, 2 = IMA-ADPCM)
        0x01 u8   loop flag
        0x02 u16  sample rate
        0x04 u16  time (u16 sample count, or 0)
        0x06 u16  loop offset, in samples
        0x08 u32  non-loop length, in samples

    Each sample is wrapped back into a normal SWAV so the rest of the tooling
    (`parse_swav`, `write_wav`) works on either source.
    """
    if data[:4] != b"SWAR" or len(data) < 0x18:
        raise SdatError("not a SWAR")
    if data[0x10:0x14] != b"DATA":
        raise SdatError("SWAR has no DATA chunk")
    count = struct.unpack_from("<H", data, 0x0E)[0]
    info = 0x18
    table = info + count * SWAR_RECORD_SIZE
    payload = table + count * 4
    if payload > len(data):
        raise SdatError("SWAR record table runs past the end")
    out: list[bytes] = []
    for i in range(count):
        base = info + i * SWAR_RECORD_SIZE
        codec = data[base]
        loop_flag = data[base + 1]
        rate, time, loop_offset = struct.unpack_from("<HHH", data, base + 2)
        length = struct.unpack_from("<I", data, base + 8)[0] or time
        start, = struct.unpack_from("<I", data, table + i * 4)
        if 0 < start < len(data) and start < payload:
            start += payload
        if start == 0:
            start = payload
        size = sample_bytes(codec, length)
        if start + size > len(data):
            size = len(data) - start
        out.append(build_swav(codec, rate, loop_flag, loop_offset, length,
                              data[start:start + size]))
    return out


def sample_bytes(codec: int, samples: int) -> int:
    """Byte length of `samples` samples in `codec`."""
    if codec == 1:
        return samples * 2
    if codec == 2:
        return (samples // 2 + 1) // 4 * 4  # IMA frames are 8 samples, 4 bytes
    return samples


def build_swav(codec: int, rate: int, loop: int, loop_offset: int,
               length: int, payload: bytes) -> bytes:
    """Wraps sample bytes in a standalone SWAV container."""
    info = struct.pack("<BBHHHI", codec, loop, rate, 0, loop_offset, length)
    total = 0x10 + 8 + len(info) + len(payload)
    return (b"SWAV" + struct.pack("<HHIHH", 0xFEFF, 0x0100, total, 0x10, 1)
            + b"DATA" + struct.pack("<I", 8 + len(info) + len(payload))
            + info + payload)


def parse_swav(data: bytes) -> dict:
    """Reads a standalone SWAV into its sample description."""
    if data[:4] != b"SWAV":
        raise SdatError("not a SWAV")
    if len(data) < 0x18 or data[0x10:0x14] != b"DATA":
        raise SdatError("SWAV has no DATA chunk")
    codec, loop_flag, sample_rate = struct.unpack_from("<BBH", data, 0x18)
    loop_start, non_loop_length = struct.unpack_from("<HI", data, 0x1E)
    samples = data[0x24:]
    return {
        "codec": codec,
        "loop": bool(loop_flag),
        "sample_rate": sample_rate or 32768,
        "loop_start": loop_start,
        "non_loop_length": non_loop_length,
        "data": samples,
    }


IMA_INDEX = [
    -1, -1, -1, -1, 2, 4, 6, 8,
    -1, -1, -1, -1, 2, 4, 6, 8,
]
IMA_STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544,
    598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878,
    2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894,
    6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
    18500, 20350, 22385, 24623, 27086, 29794, 32767,
]


def decode_adpcm(data: bytes) -> bytes:
    """Decodes Nintendo DS IMA-ADPCM into 16-bit little-endian PCM."""
    out = bytearray()
    pos = 0
    while pos + 4 <= len(data):
        header = data[pos]
        step_index = data[pos + 1]
        predictor = struct.unpack_from("<h", data, pos + 2)[0]
        pos += 4
        if step_index > 88:
            step_index = 88
        for nibble in data[pos:pos + 4]:
            for half in (nibble & 0x0F, nibble >> 4):
                step = IMA_STEP[step_index]
                diff = step >> 3
                if half & 1:
                    diff += step >> 2
                if half & 2:
                    diff += step >> 1
                if half & 4:
                    diff += step
                if half & 8:
                    predictor -= diff
                else:
                    predictor += diff
                predictor = max(-32768, min(32767, predictor))
                step_index += IMA_INDEX[half & 7]
                step_index = max(0, min(88, step_index))
                out += struct.pack("<h", predictor)
        pos += 4
    return bytes(out)


def write_wav(path, sample: dict) -> None:
    """Writes one SWAV as a mono 16-bit WAV."""
    codec = sample["codec"]
    data = sample["data"]
    rate = sample["sample_rate"]
    if codec == 0:       # PCM8
        pcm = bytearray()
        for byte in data:
            pcm += struct.pack("<h", (byte - 128) << 8)
    elif codec == 1:     # PCM16
        pcm = bytearray(data)
    elif codec == 2:     # IMA-ADPCM
        pcm = bytearray(decode_adpcm(data))
    else:
        raise SdatError(f"unsupported SWAV codec {codec}")
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(bytes(pcm))

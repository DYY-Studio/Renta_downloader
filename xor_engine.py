import importlib.util
import aiofiles
import asyncio

from pathlib import Path
from itertools import cycle

class XorEngine:
    def __init__(self):
        if importlib.util.find_spec("numpy") is not None:
            self.xor_engine = self._xor_numpy
            self.USING_NUMPY = True
        else:
            self.xor_engine = self._xor_pure_python
            self.USING_NUMPY = False

    def _xor_pure_python(self, data: bytes, key: bytes, offset: int) -> bytearray:
        key_len = len(key)
        start_pos = offset % key_len
        rotated_key = key[start_pos:] + key[:start_pos]
        key_cycle = cycle(rotated_key)
        return bytearray(b ^ next(key_cycle) for b in data)

    def _xor_numpy(self, data: bytes, key: bytes, offset: int) -> bytes:
        import numpy as np
        data_arr = np.frombuffer(data, dtype=np.uint8)
        key_arr = np.frombuffer(key, dtype=np.uint8)
        
        shift = offset % len(key_arr)
        aligned_key = np.roll(key_arr, -shift)
        
        full_key_arr = np.resize(aligned_key, len(data_arr))
        return np.bitwise_xor(data_arr, full_key_arr).tobytes()
    
    async def async_process_file(self, input_path: Path, output_path: Path, key: bytes, chunk_size=1024*1024):
        async with aiofiles.open(input_path, 'rb') as f_in, aiofiles.open(output_path, 'wb') as f_out:
            current_offset = 0
            while True:
                chunk = await f_in.read(chunk_size)
                if not chunk:
                    break
                
                processed_chunk: bytes | bytearray = await asyncio.to_thread(
                    self.xor_engine, chunk, key, current_offset
                )
                await f_out.write(processed_chunk)
                current_offset += len(chunk)

    def process_file(self, input_path: Path, output_path: Path, key: bytes, chunk_size=1024*1024):
        with open(input_path, 'rb') as f_in, open(output_path, 'wb') as f_out:
            current_offset = 0
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    break
                
                processed_chunk: bytes | bytearray = self.xor_engine(chunk, key, current_offset)
                f_out.write(processed_chunk)
                current_offset += len(chunk)
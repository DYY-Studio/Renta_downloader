import httpx
import asyncio
import base64
import re
import zipfile
import aiofiles
import shutil
import secrets
import hashlib
import json
import importlib.util
from itertools import cycle
from datetime import datetime, UTC

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from http import cookiejar
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from pathlib import Path
from dataclasses import dataclass, fields
from typing import Optional

def getLegalPath(rawPath: str) -> str:

    replacedPath = rawPath

    def getFullwidth(char: str) -> str:
        if len(char) != 1: return char
        if not ord(char) in range(0x20, 0x80):
            return char
        else:
            return chr(ord(char) - 0x20 + 0xFF00)
        
    for m in re.finditer(r'[\\/:*?"<>|\r\n]', rawPath):
        replacedPath = replacedPath[:m.start()] + getFullwidth(m.group()) + replacedPath[m.end():]
    
    return replacedPath

def EVP_BytesToKey(password: str, salt: bytes, key_len=32, iv_len=16):
    dtot = b""
    last = b""
    while len(dtot) < (key_len + iv_len):
        last = hashlib.md5(last + password.encode('utf-8') + salt).digest()
        dtot += last
    
    return dtot[:key_len], dtot[key_len:key_len + iv_len]

def decode_cryptojs_json(cjson: dict[str, str], password: str):
    ciphertext = base64.b64decode(cjson['ct'])
    salt = bytes.fromhex(cjson['s'])
    key, iv = EVP_BytesToKey(password, salt, key_len=32, iv_len=16)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted_data = unpad(cipher.decrypt(ciphertext), AES.block_size)

    return decrypted_data.decode('utf-8')

@dataclass
class RentaTaiwanAWSXHR:
	ext: str
	move: str
	overview: int
	openlr: int
	maxpage: int
	viewer: str
	key: str
	prd_id: str
	path: str
	mode: str
	rt_id: str
	user_id: str
	lim_ymd: str
	cookiekey: str
	siori_id: str
	dimension: list[str]
	site_top: str
	site_item: str
	site_item_smpl: str
	msg_foot: str
	msg_foot_smpl: str
	language: str
	confirm_msg: str
	backbutton_msg: str
	method: str
	siori: str

@dataclass
class RentaTaiwanTitleInfo:
    sid: int
    sname: str
    author: str
    is_adult: int
    actor: str
    director: str
    sales_region: str
    quality: str
    language: str
    year: str
    duration: str
    brand: str
    show_preview: bool
    is_preorder: bool
    preorder_waiting_message: str
    tid: int
    tname: str
    detail: str
    category: str
    reg_dt: Optional[str] # str | None
    type_id: int
    vol: int
    page: int
    price_48h: int
    price_buy: int
    upgrade: int
    end: Optional[str] # str | None
    safe_tname: str
    safe_sname: str
    imghv: str
    img: str
    item_c: str

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            target_type = field.type
            
            if not isinstance(value, target_type):
                try:
                    setattr(self, field.name, target_type(value))
                except (ValueError, TypeError):
                    raise

@dataclass
class RentaTaiwanDiscountTitle:
    @dataclass
    class Price:
        price: int
        final_price: int
        is_vip_free: bool | None = None

    @dataclass 
    class RentalInfo:
        status: int
    
    title_id: int
    series_id:int
    vol_no: int
    must_buy_all: bool
    rental_plan: Price
    upgrade_plan: Price
    buy_plan: Price
    buy_all_plan: Price
    rentalInfo: RentalInfo

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            target_type = field.type
            
            if not isinstance(value, target_type):
                try:
                    if isinstance(value, dict):
                        setattr(self, field.name, target_type(**value))
                    elif isinstance(value, list):
                        setattr(self, field.name, target_type(*value))
                    else:
                        setattr(self, field.name, target_type(value))
                except (ValueError, TypeError):
                    raise

@dataclass
class RentaTaiwanAppSeriesRecord:
    @dataclass
    class Title:
        vol_no: int
        id: int
        name: str
        brief_name: int
        sample: bool
        detail: str
        page: int
        status: int
        price_48h: int
        price_buy: int
        duration: int
        start: str # 上架日期
        sale_price_48h: int
        sale_price_buy: int

        is_free: bool
        is_vip_free: bool
        is_discounted: bool

        order_dt: str | None = None
        return_dt: str | None = None

        def __init__(self, **kwargs):
            names = {f.name for f in fields(self)}
            for k, v in kwargs.items():
                if k in names:
                    setattr(self, k, v)

    price_buyall: int
    latest_published_vol: str
    latest_published_date: str
    name: str
    name_alias: str
    author: list[str]
    sid: int
    status: int
    type_id: int
    is_adult: bool
    category_name: str
    category_group: str
    detail: str
    brand_name: str
    buyall_rate: int
    tags: list[str]
    titles: list[Title]

    def __init__(self, **kwargs):
        names = {f.name for f in fields(self)}
        for k, v in kwargs.items():
            if k in names:
                setattr(self, k, v)

        for field in fields(self):
            if field.name == 'titles': continue
            value = getattr(self, field.name)
            target_type = field.type
            
            try:
                if not isinstance(value, target_type):
                    if isinstance(value, dict):
                        setattr(self, field.name, target_type(**value))
                    elif isinstance(value, list):
                        setattr(self, field.name, target_type(*value))
                    else:
                        setattr(self, field.name, target_type(value))
            except (ValueError, TypeError):
                pass
            
        if getattr(self, "titles", []):
            for i in range(len(self.titles)):
                self.titles[i] = self.Title(**self.titles[i])

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

class RentaTaiwanAppAuth(httpx.Auth):
    def __init__(self, token: str, refresh_token: str, user_agent: str = "Dart/3.7 (dart:io)", app_version: int = 74):
        self.token = token
        self.refresh_token = refresh_token
        self.user_agent = user_agent
        self.app_version = app_version

    async def async_auth_flow(self, request):
        if self.token:
            request.headers['Authorization'] = f'Bearer {self.token}'
        response: httpx.Response = yield request

        if response.status_code == 401:
            refresh_response = yield self.build_refresh_request()
            await self.update_tokens(refresh_response)

            request.headers["Authorization"] = f'Bearer {self.token}'
            yield request

    def build_refresh_request(self):
        refreshCookies = {
            'auth': self.refresh_token,
            'Max-Age': '604800',
            'Path': '/'
        }
        return httpx.Request(
            'POST',
            'https://bff.myrenta.com/refresh',
            headers={
                "User-Agent": self.user_agent,
                'x-app-version': str(self.app_version)
            },
            cookies=refreshCookies
        )
    
    async def update_tokens(self, response: httpx.Response):
        self.token = json.loads(await response.aread())['accessToken']
    

class RentaTaiwanClient:
    WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
    MOBILE_USER_AGENT = "Dart/3.7 (dart:io)"
    MOBILE_APP_VERSION = '74'

    MOBILE_APP_TOKEN_CACHE = Path('renta_taiwan_mobile_info.txt')

    def __init__(self, 
        client: httpx.AsyncClient | None = None, 
        cookies: cookiejar.CookieJar | None = None,
        proxy: str | None = None,
        mobile: bool = False
    ):
        if not client:
            self.client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.WEB_USER_AGENT.replace(
                        '149.0',
                        secrets.choice((
                            '149.0', '148.0', '147.0', '146.0', '145.0', '144.0', '143.0', '142.0', 
                        ))
                    ) if not mobile else self.MOBILE_USER_AGENT
                },
                transport=httpx.AsyncHTTPTransport(retries=3),
                cookies=cookies if not mobile else None,
                timeout=20.0,
                proxy=proxy
            )
            if mobile and self.MOBILE_APP_TOKEN_CACHE.exists() and (tokens := self.MOBILE_APP_TOKEN_CACHE.read_text()):
                self.client.auth = RentaTaiwanAppAuth(*(tokens.split('\n')[:2]), user_agent=self.MOBILE_USER_AGENT, app_version=self.MOBILE_APP_VERSION)
        else:
            self.client = client

    async def check_login_web(self) -> bool:
        test = await self.client.get(
            'https://tw.myrenta.com/renta/sc/ssl/account.cgi'
        )
        if test.status_code != 302:
            test.raise_for_status()
            return True
        else:
            return False
        
    async def check_login_mobile(self) -> bool:
        test = await self.client.post(
            'https://bff.myrenta.com/me'
        )
        if test.status_code == 401:
            return False
        else:
            test.raise_for_status()
            return True

    async def login_web(self, email: str, password: str) -> bool:
        test = await self.client.get(
            f'https://secure.myrenta.com/renta/sc/ssl/login.cgi?tgt=https%3A%2F%2Ftw.myrenta.com%2F',
        )
        test.raise_for_status()

        res = await self.client.post(
            'https://secure.myrenta.com/renta/sc/ssl/login.cgi',
            data={
                "mode": "std",
                "salt": "vk_rptvnu824nerfmwke09rtm5",
                "id": email,
                "pw": password,
                "tgt": "https://tw.myrenta.com/"
            },
        )
        res.raise_for_status()
        return True

    async def login_mobile(self, email: str, password: str) -> bool:
        res = await self.client.post(
            'https://bff.myrenta.com/login',
            data={
                'email': email,
                'password': password
            }
        )
        res.raise_for_status()

        res_json = res.json()

        self.client.auth = RentaTaiwanAppAuth(
            res_json['accessToken'], res_json['refreshToken'],
            self.MOBILE_USER_AGENT, self.MOBILE_APP_VERSION
        )
        self.MOBILE_APP_TOKEN_CACHE.write_text(f"{res_json['accessToken']}\n{res_json['refreshToken']}")

        return True

    async def download_web(self, 
        tid: str, 
        target_dir: Path, 
        title: str | None = None,
        max_workers: int = 8, 
        progress: Optional['Progress'] = None
    ):
        sem = asyncio.Semaphore(max_workers)

        res = await self.client.get(
            f'https://tw.myrenta.com/read/{tid}/3'
        )
        res.raise_for_status()
        
        script_start = res.text.find('<script type="text/javascript">const checkIsInFlutter')
        if not script_start >= 0:
            return
        script = res.text[script_start:]

        location = re.search(r"location.replace\('(.+?)'\);", script)
        if not location:
            return

        jump_url = location.group(1)

        if 'view2_auth' in jump_url:
            res = await self.client.get(
                location.group(1)
            )
            if res.status_code != 302:
                return
            
            info = await self.client.get(
                res.headers['location']
            )
            info.raise_for_status()
            
            if not title: 
                title = re.search(r'<title>(.+)｜.*</title>', info.text).group(1).removeprefix("租閱")

            viewer_url = res.headers['location'].removesuffix('index.html')
            parts = urlsplit(viewer_url).path.strip('/').split('/')
            prd_id = parts[4]
            key = parts[3]

            dat = await self.client.post(
                viewer_url,
                data={
                    "ext": "dat",
                    "prd_id": prd_id,
                    "key": key
                }
            )
            dat.raise_for_status()
            dat = RentaTaiwanAWSXHR(**dat.json())

            cbz_lock = asyncio.Lock()

            async def page_request(page: int, ext: str, cbzHandle: zipfile.ZipFile):
                async with sem:
                    res = await self.client.post(
                        viewer_url,
                        files={
                            "ext": (None, ext),
                            "prd_id": (None, prd_id),
                            "page": (None, f"{page}"),
                            "type": (None, "8"),
                            "psss": (None, "sss"),
                        }
                    )
                    res.raise_for_status()
                    s3url = decode_cryptojs_json(res.json(), key).strip('"').replace('\\/', '/')
                    
                    img_res = await self.client.get(s3url)
                    img_res.raise_for_status()

                    async with cbz_lock:
                        with cbzHandle.open(f'{page:>04d}.{ext}', mode='w') as f:
                            f.write(img_res.content)
            
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target_dir / f"{getLegalPath(title)}.cbz", mode='w') as zf:
                tasks = [
                    asyncio.create_task(page_request(i, dat.ext, zf)) 
                    for i in range(1, int(dat.maxpage) + 1)
                ]
                if progress: task_id = progress.add_task('Download', total=len(tasks))
                for t in asyncio.as_completed(tasks):
                    await t
                    if progress: progress.advance(task_id)
                if progress: progress.remove_task(task_id)

        elif 'viewer.myrenta.com/reading/' in jump_url:
            token = httpx.URL(jump_url).params['token']

            temp_headers = self.client.headers.copy()
            temp_headers.update({
                'origin': 'https://viewer.myrenta.com',
                'referer': 'https://viewer.myrenta.com/',
                'authorization': f'Bearer {token}'
            })

            auth = await self.client.get(
                f'https://bff.myrenta.com/read/token/{tid}',
                headers=temp_headers
            )
            auth.raise_for_status()

            token = auth.text

            base_url = f'https://viewer.myrenta.com/view/{token}/1026/{tid}/'
            meta_inf = await self.client.get(
                f'{base_url}META-INF/container.xml'
            )
            meta_inf.raise_for_status()

            soup = BeautifulSoup(meta_inf.text, 'lxml')
            rootfile_path: str = soup.find('rootfile', {'media-type': 'application/oebps-package+xml'})['full-path']

            rootfile = await self.client.get(
                f'{base_url}{rootfile_path}'
            )
            rootfile.raise_for_status()

            soup = BeautifulSoup(rootfile.text, 'lxml')
            title = soup.package.metadata.find('dc:title').text or tid

            filelist: list[str] = []
            for item in soup.package.manifest.find_all('item'):
                filelist.append(f'{"/".join(rootfile_path.split("/")[:-1])}/{item["href"]}')

            zip_lock = asyncio.Lock()
            async def get_file(base_url: str, relpath: str, zipHandle: zipfile.ZipFile):
                async with sem:
                    res = await self.client.get(f"{base_url}{relpath}")
                    res.raise_for_status()

                    async with zip_lock:
                        with zipHandle.open(relpath, mode='w') as zf:
                            zf.write(res.content)

            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(
                target_dir / f"{getLegalPath(title)}.epub", mode='w', 
                compression=zipfile.ZIP_DEFLATED, compresslevel=1
            ) as zf:
                zf.writestr('mimetype', b'application/epub+zip', compress_type=zipfile.ZIP_STORED)
                zf.writestr('META-INF/container.xml', meta_inf.content)
                zf.writestr(rootfile_path, rootfile.content)

                tasks = [
                    asyncio.create_task(get_file(base_url, file, zf)) 
                    for file in filelist
                ]
                if progress: task_id = progress.add_task('Download', total=len(tasks))
                for t in asyncio.as_completed(tasks):
                    await t
                    if progress: progress.advance(task_id)
                if progress: progress.remove_task(task_id)

        elif '/read/video/' in jump_url:
            if not title:
                title = re.search(r'<title>(.+)｜.*</title>', res.text).group(1).removeprefix("租閱")

            # raise ValueError('Unsupported download type: VIDEO')
            res = await self.client.get(
                location.group(1)
            )
            res.raise_for_status()

            stream_url = re.search(r'{.*"video":"(http.*?m3u8)".*?};', res.text)
            if not stream_url:
                raise ValueError('Cannot find video stream url')
            stream_url = stream_url.group(1).replace('\\/', '/')
        
            if (excutable := shutil.which('streamlink')):
                target_dir.mkdir(parents=True, exist_ok=True)
                args = [
                    '--http-header', f'User-Agent={self.client.headers.get("User-Agent", self.WEB_USER_AGENT)}',
                    '--stream-segment-threads', '4',
                    '--output', f'{target_dir / f"{getLegalPath(title)}.mp4"}',
                ]
                for key, value in self.client.cookies.items():
                    args.extend(['--http-cookie', f'{key}={value}'])

                args.extend([stream_url, "best"])
                if (proxy := self.client._mounts.get('https://')):
                    args.extend(['--http-proxy', proxy])
                
                proc = await asyncio.subprocess.create_subprocess_exec(
                    excutable, *args
                )
                if progress:
                    progress.stop()
                await proc.communicate()
                if progress:
                    progress.start()
            elif (excutable := shutil.which('yt-dlp')):
                temp_cookies_path = Path('renta_taiwan_cookies_cache.txt')
                temp_cookies = cookiejar.MozillaCookieJar(temp_cookies_path)
                for cookie in self.client.cookies.jar:
                    temp_cookies.set_cookie(cookie)
                temp_cookies.save()

                target_dir.mkdir(parents=True, exist_ok=True)
                args = [
                    '--cookies', str(temp_cookies_path),
                    '-o', f'{target_dir / f"{getLegalPath(title)}.mp4"}',
                ]
                if (proxy := self.client._mounts.get('https://')):
                    args.extend(['--proxy', proxy])
                args.append(stream_url)
                
                proc = await asyncio.subprocess.create_subprocess_exec(
                    excutable, *args
                )
                if progress:
                    progress.stop()
                await proc.communicate()
                if progress:
                    progress.start()
                
                temp_cookies_path.unlink(missing_ok=True)
            else:
                if progress:
                    progress.console.print('[red]Cannot find HLS stream download tool[/red]')
                else:
                    print('Cannot find HLS stream download tool')
        else:
            raise ValueError('Unsupported download type')

    async def download_mobile(self, 
        tid: str, 
        target_dir: Path, 
        title: str,
        # max_workers: int = 8, 
        progress: Optional['Progress'] = None
    ):
        # sem = asyncio.Semaphore(max_workers)

        res = await self.client.get(
            f'https://bff.myrenta.com/read/token/{tid}'
        )
        res.raise_for_status()

        headers = self.client.headers.copy()
        headers.update({
            "x-read": res.text,
            "user-agent": f"renta_app/{self.MOBILE_APP_VERSION} CFNetwork/1399 Darwin/22.1.0",
        })

        xor = XorEngine()

        # async with sem:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = (target_dir / getLegalPath(title)).with_suffix('.bin')
        key = bytes([0xB5])
        async with aiofiles.open(target_file, mode='wb') as f:
            async with self.client.stream('GET', 'https://read.papy.com.tw/dl/26', headers=headers) as stream:
                task_id = None
                size = stream.headers.get('content-length')
                if progress: task_id = progress.add_task('Download', total=100)
                chunk_size = 8 * 1024
                first_chunk = True
                async for b in stream.aiter_bytes(chunk_size):
                    buf = await asyncio.to_thread(xor.xor_engine, b, key, offset=0)
                    if first_chunk and len(buf) > 1 and buf[:2] == b'\x72\xB4':
                        buf = b'PK' + buf[2:]
                        first_chunk = False
                    await f.write(buf)
                    if size and task_id:
                        progress.advance(task_id, (len(b) / int(size)) * 100)

                if progress and task_id:
                    progress.remove_task(task_id)

        async with aiofiles.open(target_file, mode='rb') as f:
            header = await f.read(4)
        
        if header == b'PK\x03\x04':
            rename_ext = None
            with zipfile.ZipFile(target_file, mode='r') as zf:
                if 'mimetype' in zf.namelist():
                    if zf.read('mimetype') == b'application/epub+zip':
                        rename_ext = '.epub'
            if rename_ext:
                target_file.rename(target_file.with_suffix(rename_ext))
            else:
                target_file.rename(target_file.with_suffix('.zip'))

    async def get_title_list(self, sid: str | int) -> list[RentaTaiwanTitleInfo]:
        res = await self.client.get(f'https://tw.myrenta.com/item/{sid}')
        res.raise_for_status()
        
        titleInfos_block = re.search(r'<script type="text/javascript">.*?var titleInfos=\[(.+?)\];', res.text)
        if not titleInfos_block:
            return
        
        titleInfos: list[RentaTaiwanTitleInfo] = []
        for product in re.findall(r'({.+?})[,$]', titleInfos_block.group(1)):
            titleInfo = dict()
            for item in re.findall(r'(".+?":(?:"(?:.*?)"|(?:.+?)))[,}]', product):
                titleInfo.update(json.loads('{' + item + '}'))
        
            titleInfos.append(RentaTaiwanTitleInfo(**titleInfo))

        return titleInfos
    
    async def get_title_list_mobile(self, sid: str | int) -> RentaTaiwanAppSeriesRecord:
        headers = self.client.headers.copy()
        res = await self.client.post(
            "https://bff.myrenta.com/items",
            json={
                "include_user_info": True,
                "list": [str(sid)],
            },
            headers=headers
        )
        res.raise_for_status()

        return RentaTaiwanAppSeriesRecord(**(res.json()['records'][0]))

    async def get_series_discount(self, sid: str | int) -> dict[int, RentaTaiwanDiscountTitle]:
        res = await self.client.get(
            "https://tw.myrenta.com/modules/api/discountTitlesFromSeries.php",
            params={
                "series": sid,
                "datetime": ""
            }
        )
        res.raise_for_status()
        res_json = res.json()
        if res_json['code'] == 0:
            return {item['title_id']: RentaTaiwanDiscountTitle(**item) for item in res_json['data']}
        else:
            raise RuntimeError(f"Cannot get discount info, ERROR:{res_json['code']}, MSG:{res_json['message']}")

if __name__ == "__main__":
    import typer
    from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn
    from rich.console import Console
    from rich.table import Table, Column

    app = typer.Typer()
    web_app = typer.Typer()
    mobile_app = typer.Typer()

    app.add_typer(web_app, name='web', help='Access via Renta! Taiwan Web (Compressed Comic Images. Animation download.)')
    app.add_typer(mobile_app, name='app', help='Access via Renta! Taiwan iOS App (Raw Comic Images)')

    console = Console()

    COOKIE_CACHE_FILE = Path('renta_taiwan_cookies.lwp')
    COOKIE_CACHE = cookiejar.LWPCookieJar(COOKIE_CACHE_FILE)

    CONFIG_FILE = Path('renta_taiwan_config.json')
    global_config = {
        'proxy': None
    }

    def save_cookies(jar: cookiejar.CookieJar):
        for cookie in jar:
            COOKIE_CACHE.set_cookie(cookie)
        COOKIE_CACHE.save()

    def save_config():
        global global_config
        with open(CONFIG_FILE, mode='w', encoding='utf-8') as f:
            json.dump(global_config, f)

    def load_config():
        global global_config
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, mode='r', encoding='utf-8') as f:
                global_config = json.load(f)

    @app.command(help='Set global proxy')
    def config(proxy: str = typer.Argument(help='Your proxy URL')):
        try:
            httpx.URL(proxy)
            global_config['proxy'] = proxy
            save_config()
        except:
            raise

    @web_app.command()
    def login(
        email: str = typer.Option(prompt=True),
        password: str = typer.Option(
            prompt=True, hide_input=True
        )
    ):
        async def _internal():
            load_config()
            client = RentaTaiwanClient(proxy=global_config.get('proxy'))
            succ = await client.login_web(email, password)
            if succ:
                succ = await client.check_login_web()
                if succ:
                    for cookie in client.client.cookies.jar:
                        COOKIE_CACHE.set_cookie(cookie)
                    COOKIE_CACHE.save()
                    console.print('[green]Login success[/green]')
            else:
                console.print('[red]Login fail[/red]')

        asyncio.run(_internal())

    @web_app.command()
    def logout():
        COOKIE_CACHE_FILE.unlink(missing_ok=True)
        console.print('[yellow]Cookies clean[/yellow]')

    @web_app.command()
    def login_check():
        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            load_config()
            client = RentaTaiwanClient(cookies=COOKIE_CACHE, proxy=global_config.get('proxy'))
            succ = await client.check_login_web()
            if succ:
                console.print('[green]Login success[/green]')
                save_cookies(client.client.cookies.jar)
            else:
                console.print('[yellow]You have not login[/yellow]')

        asyncio.run(_internal())

    @web_app.command(help='List all works in provided series')
    def series(series_id: str = typer.Argument(
        help='tw.myrenta.com/item/[blue bold]123456[/blue bold], or just full URL'
    )):
        if (result := re.search(r"tw.myrenta.com/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)

        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            load_config()
            client = RentaTaiwanClient(cookies=COOKIE_CACHE, proxy=global_config.get('proxy'))

            res = await client.get_title_list(series_id)
            if not res:
                console.print(f'[red]ERROR: BAD SeriesID {series_id}[/red]')
                return
            
            discount = await client.get_series_discount(series_id)

            table = Table(
                "NO.", "TID", "Title", "Region", "Price",
                title=res[0].sname,
                show_lines=True,
                caption='[green]Green[/green]: Bought\n[yellow]Yellow[/yellow]: Free'
            )
            for prd in res:
                if prd.tid not in discount:
                    discount[prd.tid] = RentaTaiwanDiscountTitle(
                        prd.tid,
                        prd.sid,
                        prd.vol,
                        False,
                        RentaTaiwanDiscountTitle.Price(prd.price_48h, prd.price_48h),
                        RentaTaiwanDiscountTitle.Price(prd.price_buy - prd.price_48h, prd.price_buy - prd.price_48h),
                        RentaTaiwanDiscountTitle.Price(prd.price_buy, prd.price_buy),
                        RentaTaiwanDiscountTitle.Price(prd.price_buy, prd.price_buy),
                        RentaTaiwanDiscountTitle.RentalInfo(0)
                    )
                buy_plan = discount[prd.tid].buy_plan
                rent_plan = discount[prd.tid].rental_plan
                table.add_row(
                    str(prd.vol), str(prd.tid), prd.tname, prd.sales_region, 
                    f"{buy_plan.final_price * 10} TWD\n"
                    f"{(str(rent_plan.final_price * 10) + ' TWD') if rent_plan.final_price >= 0 else 'NoRent'}",
                    style={
                        3: 'green',
                        2: '',
                        1: '',
                        0: ''
                    }[discount[prd.tid].rentalInfo.status] or 'yellow' if not (buy_plan.final_price or rent_plan.final_price) else ''
                )
            console.print(table)
            save_cookies(client.client.cookies.jar)
        
        asyncio.run(_internal())

    # @web_app.command()
    # def download(
    #     title_id: str = typer.Argument(
    #         help='tw.myrenta.com/item/[blue bold]123456[/blue bold], or just full URL'
    #     ),
    #     output: Path = typer.Option(Path.cwd() / 'output', help='Dir for saving files')
    # ):
    #     pass

    @web_app.command(help='Download all works that possible to download (Bought/Rented/Free) in provided series')
    def download_series(
        series_id: str = typer.Argument(
            help='tw.myrenta.com/item/[blue bold]123456[/blue bold], or just full URL'
        ),
        output: Path = typer.Option(Path.cwd() / 'output', help='Dir for saving files')
    ):
        if (result := re.search(r"tw.myrenta.com/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)
        
        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            load_config()
            client = RentaTaiwanClient(cookies=COOKIE_CACHE, proxy=global_config.get('proxy'))
            succ = await client.check_login_web()
            if not succ:
                console.print('[red]Login required[/red]')
                return
            
            res = await client.get_title_list(series_id)
            if not res:
                console.print(f'[red]ERROR: BAD SeriesID {series_id}[/red]')
                return
            
            discount = await client.get_series_discount(series_id)

            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                transient=True,
                console=console
            ) as progress:
                total_task = progress.add_task('Total', total=len(res))
                for prd in res:
                    if prd.price_buy == 0 or prd.price_48h == 0 or (prd.tid in discount and discount[prd.tid].rentalInfo.status != 0):
                        await client.download_web(prd.tid, output, prd.tname, progress=progress)
                    else:
                        console.print(f'[yellow]SKIP Unrented / Non-free [bold]{prd.tname}[/bold][/yellow]')
                    progress.advance(total_task)
            save_cookies(client.client.cookies.jar)
        
        asyncio.run(_internal())

    @mobile_app.command('login')
    def login_mobile(
        email: str = typer.Option(prompt=True),
        password: str = typer.Option(
            prompt=True, hide_input=True
        )
    ):
        async def _internal():
            load_config()
            client = RentaTaiwanClient(proxy=global_config.get('proxy'), mobile=True)
            succ = await client.login_mobile(email, password)
            if succ:
                succ = await client.check_login_mobile()
                if succ:
                    console.print('[green]Login success[/green]')
                    return
            console.print('[red]Login fail[/red]')

        asyncio.run(_internal())

    @mobile_app.command('logout')
    def logout_mobile():
        RentaTaiwanClient.MOBILE_APP_TOKEN_CACHE.unlink(missing_ok=True)
        console.print('[yellow]Token cache clean[/yellow]')

    @mobile_app.command('login-check')
    def login_check_mobile():
        async def _internal():
            load_config()
            client = RentaTaiwanClient(proxy=global_config.get('proxy'), mobile=True)
            succ = await client.check_login_mobile()
            if succ:
                console.print('[green]Login success[/green]')
            else:
                console.print('[yellow]You have not login[/yellow]')

        asyncio.run(_internal())

    @mobile_app.command('series', help='List all works in provided series')
    def series_mobile(series_id: str = typer.Argument(
        help='tw.myrenta.com/item/[blue bold]123456[/blue bold], or just full URL'
    )):
        if (result := re.search(r"tw.myrenta.com/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)

        async def _internal():
            load_config()
            client = RentaTaiwanClient(proxy=global_config.get('proxy'), mobile=True)

            succ = await client.check_login_mobile()
            if not succ:
                console.print('[red]Login required[/red]')
                return

            res = await client.get_title_list_mobile(series_id)
            if not res:
                console.print(f'[red]ERROR: BAD SeriesID {series_id}[/red]')
                return

            table = Table(
                "NO.", "TID", "Title", "Price",
                title=res.name,
                show_lines=True,
                caption='[green]Green[/green]: Bought\n[yellow]Yellow[/yellow]: Free'
            )
            for prd in res.titles:
                table.add_row(
                    str(prd.vol_no), 
                    str(prd.id), 
                    prd.name, 
                    f"{(prd.sale_price_buy if prd.sale_price_buy >= 0 else prd.sale_price_48h) / 100:.1f}",
                    style='green' if prd.return_dt and datetime.now(UTC) < datetime.fromisoformat(prd.return_dt + '+00:00') else (
                        'yellow' if prd.is_free or prd.is_vip_free else ''
                    )
                )
            console.print(table)
        
        asyncio.run(_internal())

    @mobile_app.command('download-series', help='')
    def download_series_mobile( series_id: str = typer.Argument(
            help='tw.myrenta.com/item/[blue bold]123456[/blue bold], or just full URL'
        ),
        output: Path = typer.Option(Path.cwd() / 'output', help='Dir for saving files')
    ):
        if (result := re.search(r"tw.myrenta.com/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)
        
        async def _internal():
            load_config()
            client = RentaTaiwanClient(proxy=global_config.get('proxy'), mobile=True)
            succ = await client.check_login_mobile()
            if not succ:
                console.print('[red]Login required[/red]')
                return
            
            res = await client.get_title_list_mobile(series_id)
            if not res:
                console.print(f'[red]ERROR: BAD SeriesID {series_id}[/red]')
                return
            
            if res.category_group == '影片':
                console.print(f'[yellow]Cannot download Animation in App Mode[/yellow]')
                return

            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                transient=True,
                console=console
            ) as progress:
                total_task = progress.add_task('Total', total=len(res.titles))
                for prd in res.titles:
                    if prd.is_free or prd.is_vip_free or (prd.return_dt and datetime.now(UTC) < datetime.fromisoformat(prd.return_dt + '+00:00')):
                        await client.download_mobile(prd.id, output, prd.name, progress=progress)
                        console.print(f'[green]Downloaded [bold]{prd.name}[/bold][green]')
                    else:
                        console.print(f'[yellow]SKIP Unrented / Non-free [bold]{prd.name}[/bold][/yellow]')
                    progress.advance(total_task)
        
        asyncio.run(_internal())

    app()
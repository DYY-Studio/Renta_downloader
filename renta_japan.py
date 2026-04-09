import httpx
import asyncio
import aiofiles
import base64
import re
import io
import zipfile
import shutil
import secrets

from http import cookiejar
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup
from pathlib import Path
from dataclasses import dataclass, fields
from typing import Literal, Any, AsyncGenerator, Union
from PIL import Image

from enovel2epub import ENovelEpubBuilder

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

@dataclass
class MedusaEpubMeta:
    relpath: str
    img_width: int
    img_height: int
    curr_idx: int
    next_idx: int
    total: int

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
class MedusaPackMeta:
    ext: str
    title: str 
    link: str 
    description: str 
    image: str 
    limit_dt: str 
    view_type: str 
    title_kana: str 
    author: str 
    author_kana: str 
    genre: str
    series_id: str 
    volume: str 
    bcg: Literal['b', 'c', 'g'] 
    series_name: str 
    series_name_kana: str 
    keyword: str 
    rating: str 
    tid: str 
    url_base: str 
    url_jump: str 
    user_id: str 
    rt_id: str 
    siori_id: str
    deliver_hash: str 
    cookie_hash: str 
    url_idx: str 
    url_dat: str

    # when bcg == 'c'
    openlr: str | None = None
    encode: str | None = None
    page_max: str | None = None
    page: str | None = None

class MedusaRedirectTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request):
        response = await super().handle_async_request(request)
        
        if "location" in response.headers:
            location = response.headers["location"]
            if "://" in location and location.lower().startswith("medusa://"):
                clean_url = location.split("://", 1)[-1].removeprefix('req_dev_id=')
                response.headers["location"] = clean_url
                
        return response

class RentaGetTitleListResponse:
    @dataclass
    class Series:
        all_cnt: int
        buy_cnt: int
        cnt_unit: int
        wayomi: bool
        btn_str_type: str
        end: bool
        sales_end: bool
        test: bool
        series_name: str

    @dataclass
    class Title:
        prd_no: int
        prd_name: str
        is_show: bool
        is_buy: bool
        is_view: bool
        is_dl: bool
        is_dl_only: bool
        is_free: bool
        status: int
        shelf_id: int
        dt_release: str
        is_set: int
        is_device_ng: int
        is_another: bool
        
        prd_tid: str

        dt_lmt: str | None = None

    serise: Series
    title: list[Title] # dict[str<no.>, dict[str<tid>, dict[str, Any]]]

    def __init__(self, series: dict[str, Any], title: dict[str, dict[str, dict[str, Any]]]):
        self.serise = self.Series(**series)
        self.title = list()
        for v in title.values():
            for tid, item in v.items():
                self.title.append(self.Title(prd_tid=tid, **item))

class RentaJSImgDescrambler:
    @staticmethod
    def f_shuffle_r(matrix: list[list[int]], t: int, col_idx: int, n: int) -> list[list[int]]:
        """
        基于列的交叉洗牌逻辑

        :param matrix: 完成准备工作的映射矩阵
        :type matrix: list[list[int]]
        :param t: 洗牌次数
        :type t: int
        :param col_idx: 列索引
        :type col_idx: int
        :param n: 矩阵大小
        :type n: int
        :return: 完成洗牌的映射矩阵
        :rtype: list[list[int]]
        """
        rn = n // 2
        if n % 2 != 0:
            rn += 1
        kn = n // 2
        
        i_arr = [None] * rn
        o_arr = [None] * kn
        s_arr = [None] * n
        
        l_ptr = 0
        k_cnt = 0
        d_ptr = 0
        
        # 基于奇偶下标拆分并交叉合并
        if t % 2 == 0:
            for c in range(n):
                if c % 2 == 0:
                    i_arr[l_ptr] = matrix[c][col_idx]
                    l_ptr += 1
                else:
                    o_arr[k_cnt] = matrix[c][col_idx]
                    k_cnt += 1
            
            for c in range(rn):
                if c < len(o_arr) and o_arr[c] is not None:
                    s_arr[d_ptr] = o_arr[c]
                    d_ptr += 1
                if c < len(i_arr) and i_arr[c] is not None:
                    s_arr[d_ptr] = i_arr[c]
                    d_ptr += 1
        
        # 基于前后半段拆分并交叉合并
        else:
            for c in range(n):
                if c < rn:
                    i_arr[l_ptr] = matrix[c][col_idx]
                    l_ptr += 1
                else:
                    o_arr[k_cnt] = matrix[c][col_idx]
                    k_cnt += 1
                    
            for c in range(rn):
                if c < len(i_arr) and i_arr[c] is not None:
                    s_arr[d_ptr] = i_arr[c]
                    d_ptr += 1
                if c < len(o_arr) and o_arr[c] is not None:
                    s_arr[d_ptr] = o_arr[c]
                    d_ptr += 1
                    
        # 将洗牌后的结果写回原矩阵的对应列
        for c in range(n):
            matrix[c][col_idx] = s_arr[c]
        
        return matrix

    @staticmethod
    def get_coordinate_map(e: int, prd_tid: int) -> dict[int, tuple[int, int]]:
        """
        获取分块映射表

        :param e: 页码
        :type e: int
        :param prd_tid: 作品Titie ID
        :type prd_tid: int
        :return: 映射表
        :rtype: dict[int, tuple[int, int]]
        """
        grid_size = 7
        # 初始化 7x7 矩阵，填入 0-48
        y = [[0 for _ in range(grid_size)] for _ in range(grid_size)]
        count = 0
        for i in range(grid_size):
            for w in range(grid_size):
                y[i][w] = count
                count += 1

        # 基础行变换
        for i in range(grid_size):
            temp_row = [None] * grid_size
            offset = grid_size - (i % grid_size)
            for w in range(grid_size):
                if offset >= grid_size:
                    offset = 0
                temp_row[w] = y[i][offset]
                offset += 1
            y[i] = temp_row

        # 基础列变换
        for i in range(grid_size):
            temp_col = [None] * grid_size
            offset = grid_size - (i % grid_size)
            for w in range(grid_size):
                if offset >= grid_size:
                    offset = 0
                temp_col[w] = y[offset][i]
                offset += 1
            for w in range(grid_size):
                y[w][i] = temp_col[w]

        # 计算动态因子 I
        I = int(e) + int(prd_tid)
        if I % 20 == 0:
            I = abs(int(e) - int(prd_tid)) + 21
        
        for i in range(grid_size):
            C = i + 1
            # 计算每一列的洗牌次数 w_limit
            w_limit = int(((C * I + e / 20) % 20)) - 1
            for w in range(w_limit, -1, -1):
                y = RentaJSImgDescrambler.f_shuffle_r(y, w, i, grid_size)

        # 生成最终的映射表
        # x[b] = [col, row] 表示第 b 个切片应该放在 (col, row) 位置
        x_map = {}
        for i in range(grid_size):
            for w in range(grid_size):
                tile_index = y[i][w]
                x_map[tile_index] = (w, i) # (x坐标, y坐标)
                
        return x_map

    @staticmethod
    def descramble(f: io.BufferedIOBase, img_idx: int, tid: int, save_dir: Path, img_fmt: str = 'png', **kwards) -> Path:
        meta_length = int(f.read(9).decode())
        metadata = f.read(meta_length).decode().split('|')

        orig_width = int(metadata[0])
        orig_height = int(metadata[1])
        data_ranges: list[tuple[int, int]] = [tuple(int(i) for i in s.rstrip(',').split(',')) for s in metadata[2:]]

        segment_count = 0

        final_image = Image.new('RGB', (orig_width, orig_height))
        seg_width = orig_width // 7
        seg_height = orig_height // 7
        
        mapping = RentaJSImgDescrambler.get_coordinate_map(img_idx, tid)

        x_offset = orig_width % 7
        y_offset = orig_height % 7

        # idx_offset = 0 

        # split by metadata
        for idx, loc in enumerate(data_ranges):
            if len(loc) == 1:
                continue
            pos, size = loc
            f.seek(meta_length + 9 + pos)
            with io.BytesIO(f.read(size)) as buffer:
                with Image.open(buffer) as seg_img:
                    if idx == 0:
                        final_image.paste(seg_img, (0, 0))
                        # idx_offset += 1
                    elif idx == 1:
                        final_image.paste(seg_img, (0, 0))
                        # idx_offset += 1
                    else:
                        final_image.paste(seg_img, (
                            mapping[idx - 2][0] * seg_width + x_offset, 
                            mapping[idx - 2][1] * seg_height + y_offset)
                        )

            segment_count += 1

        final_image.save((save_path := save_dir / f'{img_idx:>04d}.{img_fmt}'), format=img_fmt, **kwards)
        return save_path

class RentaJapanClient:
    # WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
    MOBILE_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) MedusaBookReader/5.7.6"

    def __init__(self, 
        client: httpx.AsyncClient | None = None, 
        cookies: cookiejar.CookieJar | None = None,
        proxy: str | None = None
    ):
        if not client:
            self.client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.MOBILE_USER_AGENT.replace(
                        '26_0_1', 
                        secrets.choice((
                            '26_0', '26_0_1', '26_1', '26_2', '26_3', '26_4',
                            '18_7', '18_7_1', '18_7_2', '18_7_3', '18_7_4', '18_7_5', '18_7_6'
                        ))
                    )
                },
                transport=MedusaRedirectTransport(proxy=proxy, retries=3),
                cookies=cookies,
                timeout=20.0
            )
        else:
            self.client = client

    async def check_login(self) -> bool:
        test = await self.client.get(
            'https://renta.papy.co.jp/renta/sc/frm/mypage/'
        )
        if test.status_code != 302:
            test.raise_for_status()
            return True
        else:
            return False

    async def login_mobile(self, email: str, password: str) -> bool:
        test = await self.client.get(
            f'https://acr4-a1.papy.co.jp/renta/sc/ssl/login.cgi?tgt=https://renta.papy.co.jp%2Frenta%2Fsc%2Ffrm%2Fmypage%2F',
        )
        test.raise_for_status()

        res = await self.client.post(
            'https://acr4-a1.papy.co.jp/renta/sc/ssl/login.cgi',
            data={
                "mode": "<!--#dt:mode-->",
                "id": email,
                "pw": password
            },
        )
        if res.status_code != 302:
            raise ValueError(res.text)
        elif str(res.next_request.url) == "https://renta.papy.co.jp/renta/sc/frm/mypage/":
            return True
        else:
            return False

    async def login_web(self, email: str, password: str) -> bool:
        test = await self.client.get(
            f'https://acr1.papy.co.jp/renta/sc/ssl/login.cgi?tgt=https%3A%2F%2Frenta.papy.co.jp%2F',
        )
        test.raise_for_status()

        res = await self.client.post(
            'https://acr1.papy.co.jp/renta/sc/ssl/login.cgi',
            data={
                "mode": "<!--#dt:mode-->",
                "id": email,
                "pw": password
            },
        )
        if res.status_code != 302:
            raise ValueError(res.text)
        elif res.headers.get('location') == 'https://renta.papy.co.jp/':
            return True
        else:
            return False
        
    async def get_title_list(self, series_id: str) -> RentaGetTitleListResponse:
        res = await self.client.get(
            'https://renta.papy.co.jp/renta/sc/rent/get_title_list.cgi',
            params={
                "series_id": series_id,
                "mode": "collection",
                "type": "cover",
                "sort": "no_asc",
                "touch": "1"
            }
        )
        res.raise_for_status()
        return RentaGetTitleListResponse(**res.json())
    
    async def read_free(self, prd_tid: str) -> httpx.URL | None:
        res = await self.client.get(
            'https://renta.papy.co.jp/renta/sc/read_free.cgi',
            params={
                'prd_tid': prd_tid
            }
        )
        res.raise_for_status()

        soup = BeautifulSoup(res.text, 'lxml')
        target = soup.head.find('meta', {'http-equiv': 'refresh'})
        if target:
            res = await self.client.get(
                target['content'].split(';')[1].strip().removeprefix('URL='),
                follow_redirects=True
            )
            return res.url
        else:
            return None
        
    async def jump_viewer(self, prd_tid: str, style: str = 'ch') -> httpx.URL | None:
        try:
            res = await self.client.get(
                'https://renta.papy.co.jp/renta/sc/jump/read/',
                params={
                    'prd_tid': prd_tid,
                    'style': style,
                    'Medusa': 'on'
                },
                follow_redirects=True,
            )

            res.raise_for_status()

            if (text := res.text):
                soup = BeautifulSoup(text, 'lxml')
                if soup.head and 'ポイント使用確認画面' in soup.head.title.text:
                    return None
                else:
                    return res.url
            else:
                return res.url
        except Exception as e:
            res = await self.client.get(
                'https://renta.papy.co.jp/renta/sc/jump/read/',
                params={
                    'prd_tid': prd_tid,
                    'style': style,
                    # 'Medusa': 'on'
                },
                follow_redirects=True
            )

            res.raise_for_status()

            soup = BeautifulSoup(res.text, 'lxml')
            target = soup.head.find('meta', {'http-equiv': 'refresh'})
            if target:
                res = await self.client.get(
                    target['content'].split(';')[1].strip().removeprefix('URL='),
                    follow_redirects=True
                )
                return res.url
            else:
                return None
    
    @staticmethod
    def medusa_epub_parser(f: io.BytesIO) -> tuple[MedusaEpubMeta, bytes]:
        f.read(2) # unused

        header_size = int(f.read(3).decode())
        meta_b64 = re.match(r'[A-Za-z0-9+/]*', f.read(header_size).decode()).group()
        meta_b64 += '=' * (len(meta_b64) % 4)
        meta = MedusaEpubMeta(*base64.b64decode(meta_b64).decode().rstrip(', ').split(','))
        # meta = ['<relpath>', '<img_width>', '<img_height>', '<curr_idx>', '<next_idx>', '<total>']

        return meta, base64.b64decode(f.read())

    async def download(
        self, 
        viewer_url: httpx.URL, 
        target_dir: Path, 
        allow_descramble: bool = False, 
        max_workers: int = 8, 
        progress: Union['Progress', None] = None
    ) -> AsyncGenerator[tuple[str, int | None], None]:
        sem = asyncio.Semaphore(max_workers)

        async def get_epub_file(temp: Path, idx: int, save: bool = True):
            async with sem:
                url = list(urlsplit(str(viewer_url)))
                url[2] = '/'.join(url[2].split('/')[:6]) + f'/id/{idx}/'
                
                res = await self.client.get(
                    urlunsplit(url)
                )
                res.raise_for_status()
                with io.BytesIO(res.content) as b:
                    meta, content = RentaJapanClient.medusa_epub_parser(b)

                if save:
                    save_path = temp / meta.relpath
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    async with aiofiles.open(save_path, mode='wb') as f:
                        await f.write(content)

                return meta
        
        async def get_pack_file(temp: Path, url: str, ext: str, name: str, start_pos: int, size: int):
            async with sem:
                temp.mkdir(exist_ok=True, parents=True)
                async with aiofiles.open(temp / f"{name}.{ext}", mode='wb') as f:
                    range_headers = self.client.headers.copy()
                    range_headers['Range'] = f'bytes={start_pos}-{start_pos + size - 1}'
                    async with self.client.stream("GET", url, headers=range_headers) as stream:
                        async for b in stream.aiter_bytes():
                            await f.write(b)
                return f"{name}.{ext}"

        async def get_jsimg_file(temp: Path, url: str, idx: int, tid: int):
            async with sem:
                hurl = httpx.URL(url)
                res = await self.client.get(hurl)
                res.raise_for_status()
                with io.BytesIO(res.content) as f:
                    fpath = await asyncio.to_thread(
                        RentaJSImgDescrambler.descramble, f, idx, tid, temp, 'png', compress_level=1
                    )
                return fpath
            
        def zip_epub(file_path: Path, files: list[Path]):
            with zipfile.ZipFile(file_path, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
                zf.writestr('mimetype', b'application/epub+zip', compress_type=zipfile.ZIP_STORED)
                for file in files:
                    if file.name != 'mimetype':
                        zf.write(file, file.relative_to(temp_dir))
                    file.unlink(missing_ok=True)

        if viewer_url.path.startswith('/sc/view_epub2/'):
            files = list()
            temp_dir = target_dir / 'temp'
            yield 'Metadata', None
            meta = await get_epub_file(temp_dir, 0, False)
            # files.add(meta.relpath)

            opfIdx = -1
            tasks = set(asyncio.create_task(get_epub_file(temp_dir, idx)) for idx in range(1, meta.total))
            yield 'Downloading', len(tasks)
            for t in asyncio.as_completed(tasks):
                meta = await t
                files.append(meta.relpath)
                if meta.relpath.lower().endswith('.opf'):
                    opfIdx = len(files) - 1
                yield 'Downloading', len(tasks)

            file_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f.epub")
            if opfIdx > -1:
                async with aiofiles.open(temp_dir / files[opfIdx], mode='r', encoding='utf-8') as f:
                    soup = BeautifulSoup(await f.read(), 'lxml')
                title_elem = soup.find('dc:title', {'id': 'title'})
                if title_elem:
                    file_name = f"{getLegalPath(title_elem.text)}.epub"

            yield 'Packing', None
            await asyncio.to_thread(
                zip_epub, target_dir / file_name, [temp_dir / file for file in files]
            )

            shutil.rmtree(temp_dir)

        elif viewer_url.path.startswith('/sc/view_pack/'):
            yield 'Metadata', None

            res = await self.client.get(viewer_url)
            res.raise_for_status()

            meta = [item.split('\t') for item in res.text.rstrip(', ').split(',')]
            meta = MedusaPackMeta(**{item[0]: item[1] for item in meta if len(item) > 1})

            res = await self.client.get(meta.url_idx)
            res.raise_for_status()

            # tuple[<name>, <start_pos>, <size>]
            file_indexes: list[tuple[str, int, int]] = []
            for line in res.text.splitlines():
                splited = line.rstrip(',').split(',')
                file_indexes.append([splited[0], int(splited[1]), int(splited[2])])

            if meta.bcg == 'b' and len(file_indexes) == 1:
                yield 'Downloading', None
                name = await get_pack_file(target_dir, meta.url_dat, meta.ext, *file_indexes[0])
                yield 'Repacking', 1
                chunk_size = 4 * 1024
                async with aiofiles.open(target_dir / name, mode='rb') as f:
                    # 100 bytes header, targeting the index of appending zip file after main ePub
                    book_header = (await f.read(100)).decode()
                    pos1, pos2 = (int(i) for i in book_header.strip().split(','))

                    # Read main ePub, drop header and appending zip file
                    async with aiofiles.open(
                        (target_dir / getLegalPath(meta.title)).with_suffix(
                            '.epub' if meta.ext.startswith('epub') else f".{meta.ext}"
                        ), 
                        mode='wb'
                    ) as sf:
                        while len(await f.peek()) > 0:
                            if (tell := await sf.tell()) + chunk_size > pos1:
                                if (remaining := pos1 - tell) > 0:
                                    await sf.write(await f.read(remaining))
                                break
                            else:
                                await sf.write(await f.read(chunk_size))

                    # Renta! ePub TOC & PlainTexts
                    # A little zip file appended to main ePub

                    # await f.seek(pos1 + 100)
                    # async with aiofiles.open(
                    #     (target_dir / getLegalPath(meta.title)).with_suffix('.add.zip'), 
                    #     mode='wb'
                    # ) as sf:
                    #     while len(await f.peek()) > 0:
                    #         if (tell := await sf.tell()) + chunk_size > pos2:
                    #             if (remaining := pos2 - tell) > 0:
                    #                 await sf.write(await f.read(remaining))
                    #             break
                    #         else:
                    #             await sf.write(await f.read(chunk_size))
                    
                (target_dir / name).unlink(missing_ok=True)
                yield 'Repacking', 1
            else:
                yield 'Downloading', len(file_indexes)
                temp_dir = target_dir / 'temp'
                temp_dir.mkdir(parents=True, exist_ok=True)
                tasks = set(
                    asyncio.create_task(get_pack_file(temp_dir, meta.url_dat, meta.ext, *idx)) 
                    for idx in file_indexes
                )
                with zipfile.ZipFile(target_dir / f"{getLegalPath(meta.title)}.zip", mode='w') as zf:
                    for t in asyncio.as_completed(tasks):
                        name = await t
                        zf.write(temp_dir / name, name)
                        (temp_dir / name).unlink(missing_ok=True)
                        yield 'Downloading', len(file_indexes)
                shutil.rmtree(temp_dir)

        elif allow_descramble and re.match(r'/sc/view_(?:js|t)img5/', viewer_url.path):
            if progress:
                progress.console.print('[yellow bold]Warning[/yellow bold]: Scrambled images are low quality. It\'s highly recommand to turn off this feature.\n\tYou should buy/rent this work to avoid scrambled images.')
            yield 'Metadata', None

            res = await self.client.get(viewer_url)
            res.raise_for_status()

            soup = BeautifulSoup(res.text, 'lxml')
            script = soup.find_all('script')[-2].text

            prd_ser = re.search(r'prd_ser ?= ?"([0-9]+)"[,;]', script)
            set_page = re.search(r'set_page ?= ?parseInt\("([0-9]+?)"\)[,;]', script)
            max_page = re.search(r'max_page ?= ?parseInt\("([0-9]+?)"\)[,;]', script)
            auth_key = re.search(r'auth_key ?= ?"(auth-key=.+?)"[,;]', script)
            cache_update = re.search(r'cache_update ?= ?"([0-9]+)"[,;]', script)
            url_base2 = re.search(r'url_base2 ?= ?"(https://.+?)"[,;]', script)

            if not all((prd_ser, set_page, max_page, auth_key, cache_update, url_base2, )):
                yield 'ERROR', None
            else:
                prd_ser = prd_ser.group(1)
                set_page = set_page.group(1)
                max_page = max_page.group(1)
                auth_key = auth_key.group(1)
                cache_update = cache_update.group(1)
                url_base2 = url_base2.group(1)
            prd_name = re.search(r'const prdName  = "(.+?)";', script).group(1)

            def generate_urls():
                for i in range(int(set_page), int(max_page) + 1):
                    yield f'{url_base2}{i}?date={cache_update}&{auth_key}&origin=s_dre-viewer.papy.co.jp', i, int(prd_ser)
            
            temp_dir = target_dir / 'temp'
            temp_dir.mkdir(parents=True, exist_ok=True)

            self.client.headers['Origin'] = 'https://dre-viewer.papy.co.jp'
            self.client.headers['Referer'] = 'https://dre-viewer.papy.co.jp/'

            tasks = [
                asyncio.create_task(get_jsimg_file(temp_dir, *params)) 
                for params in generate_urls()
            ]
            yield 'Download', len(tasks)
            files: list[Path] = []
            for t in asyncio.as_completed(tasks):
                files.append(await t)
                yield 'Download', len(tasks)

            self.client.headers.pop('Origin')
            self.client.headers.pop('Referer')

            yield 'Packing', None
            def pack_cbz(files: list[Path], target: Path):
                with zipfile.ZipFile(target.with_suffix('.cbz'), mode='w', compression=zipfile.ZIP_STORED) as zf:
                    for file in files:
                        zf.write(file, file.relative_to(temp_dir))
            
            await asyncio.to_thread(pack_cbz, files, target_dir / f'{getLegalPath(prd_name)}_jsimg')
            
            shutil.rmtree(temp_dir)

        elif viewer_url.path.startswith('/sc/view_novel'):
            url = list(urlsplit(str(viewer_url)))
            url[2] = '/'.join(url[2].strip('/').split('/')[:5])
            base_url = urlunsplit(url).rstrip('/')
            headers = self.client.headers.copy()
            headers.update({
                'Referer': str(viewer_url),
                'X-Requested-With': 'XMLHttpRequest'
            })
            yield 'Metadata', None
            res = await self.client.get(
                base_url + '/file/',
                headers=headers
            )
            res.raise_for_status()
            main_json: list[dict[str, str | list[dict[str, str]]]] = res.json()
            
            temp_dir = target_dir / 'temp'
            temp_dir.mkdir(parents=True, exist_ok=True)

            async def simple_download(url: str, fpath: Path):
                async with sem:
                    res = await self.client.get(url)
                    res.raise_for_status()
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    async with aiofiles.open(fpath, mode='wb') as f:
                        await f.write(res.content)
                
            yield 'Generate', None
            builder = ENovelEpubBuilder(
                main_json[0]['title'], main_json[0]['message'][1]['str'].split('<br><br>')[1]
            )
            img_mapping: dict[str, Path] = await builder.build(main_json, temp_dir)

            yield 'Download', None
            tasks = [
                asyncio.create_task(
                    simple_download(base_url + f'/id/{name}', fpath)
                ) 
                for name, fpath in img_mapping.items()
            ]
            yield 'Download', len(tasks)
            for t in asyncio.as_completed(tasks):
                await t
                yield 'Download', len(tasks)

            yield 'Packing', None
            output_name = f"{getLegalPath(main_json[0]['title'])}.epub"
            temp_dir = temp_dir / 'build'
            await asyncio.to_thread(
                zip_epub, target_dir / output_name,
                [
                    f for f in temp_dir.glob('**/*') 
                    if f.is_file()
                ]
            )
            shutil.rmtree(temp_dir.parent)

        elif viewer_url.path.startswith('/sc/view_'):
            return
            # raise ValueError(f"Discouraged / Unsupported Viewer Mode: {viewer_url.path.strip('/').split('/')[1].removeprefix('view_')}")
        else:
            raise ValueError("Unknown Viewer URL")
        
if __name__ == "__main__":
    import typer
    from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn
    from rich.console import Console
    from rich.table import Table, Column

    app = typer.Typer()
    console = Console()

    COOKIE_CACHE_FILE = Path('renta_japan_cookies.lwp')
    COOKIE_CACHE = cookiejar.LWPCookieJar(COOKIE_CACHE_FILE)

    @app.command()
    def login(
        email: str = typer.Option(prompt=True),
        password: str = typer.Option(
            prompt=True, hide_input=True
        )
    ):
        async def _internal():
            client = RentaJapanClient()
            succ = await client.login_mobile(email, password)
            if succ:
                succ = await client.check_login()
                if succ:
                    for cookie in client.client.cookies.jar:
                        COOKIE_CACHE.set_cookie(cookie)
                    COOKIE_CACHE.save()
                    console.print('[green]Login success[/green]')

        asyncio.run(_internal())

    @app.command()
    def logout():
        COOKIE_CACHE_FILE.unlink(missing_ok=True)
        console.print('[yellow]Cookies clean[/yellow]')

    @app.command()
    def login_check():
        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            client = RentaJapanClient(cookies=COOKIE_CACHE)
            succ = await client.check_login()
            if succ:
                console.print('[green]Login success[/green]')
            else:
                console.print('[yellow]You have not login[/yellow]')

        asyncio.run(_internal())

    @app.command(help='List all works in provided series')
    def series(series_id: str = typer.Argument(
        help='renta.papy.co.jp/renta/sc/frm/item/[blue bold]123456[/blue bold], or just full URL'
    )):
        if (result := re.search(r"renta.papy.co.jp/renta/sc/frm/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)

        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            client = RentaJapanClient(cookies=COOKIE_CACHE)
            succ = await client.check_login()
            if not succ:
                console.print('[red]Login required[/red]')
                return
            res = await client.get_title_list(series_id)
            # console.print(res.serise, res.title)

            table = Table(
                "NO.", "TID", "Title",
                title=res.serise.series_name,
                show_lines=True,
                caption='[green]Green[/green]: Possible to download\n[yellow]Yellow[/yellow]: Read for free'
            )
            for prd in res.title:
                table.add_row(
                    str(prd.prd_no), prd.prd_tid, prd.prd_name,
                    style='green' if prd.is_dl else ('yellow' if prd.is_free else '')
                )
            console.print(table)
        
        asyncio.run(_internal())

    @app.command(help='Download all works that possible to download (Bought/Rented/Free) in provided series')
    def download_series(
        series_id: str = typer.Argument(
            help='renta.papy.co.jp/renta/sc/frm/item/[blue bold]123456[/blue bold], or just full URL'
        ),
        output: Path = typer.Option(Path.cwd() / 'output', help='Dir for saving files'),
        descramble: bool = typer.Option(False, help='Enable descrambling for free mangas\' JSImg5 View (Not recommended)'),
        proxy: str | None = typer.Option(None, help='Proxy for download')
    ):
        if (result := re.search(r"renta.papy.co.jp/renta/sc/frm/item/([0-9]+)/?", series_id)):
            series_id = result.group(1)
        else:
            series_id = int(series_id)
        
        async def _internal():
            if COOKIE_CACHE_FILE.exists():
                COOKIE_CACHE.load()
            client = RentaJapanClient(cookies=COOKIE_CACHE, proxy=proxy)
            succ = await client.check_login()
            if not succ:
                console.print('[red]Login required[/red]')
                return
            res = await client.get_title_list(series_id)

            console.print(f'[blue bold]Series: {res.serise.series_name}[/blue bold]')
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                transient=True,
                console=console
            ) as progress:
                total_task = progress.add_task('Products', total=len(res.title))
                for prd in res.title:
                    viewer_url = None
                    task_id = progress.add_task('Starting', total=None)
                    if prd.is_dl:
                        viewer_url = await client.jump_viewer(prd_tid=f"9-{prd.prd_tid}")
                    elif prd.is_free:
                        viewer_url = await client.read_free(prd_tid=f"9-{prd.prd_tid}")
                    else:
                        console.print(f'[yellow]SKIP Unbought {prd.prd_name}[/yellow]')
                        progress.advance(total_task)
                        progress.remove_task(task_id)
                        continue

                    if not viewer_url:
                        console.print(f'[red]ERROR: Cannot request viewer for {prd.prd_name}[/red]')
                        progress.advance(total_task)
                        progress.remove_task(task_id)
                        continue
                    
                    async for desc, total in client.download(
                        viewer_url, output, allow_descramble=descramble, progress=progress
                    ):
                        task = progress._tasks[task_id]
                        if task.description != desc:
                            task.description = desc
                        if task.total != total:
                            task.total = total
                        elif task.total is not None:
                            progress.advance(task_id)
                    if progress._tasks[task_id].description != 'Starting':
                        console.print(f'[green]Downloaded {prd.prd_name}[/green]')
                    else:
                        console.print(f'[yellow]Not recommended / Unsupported View {prd.prd_name}[/yellow]')
                        console.print(f'\t{viewer_url.path}')
                        console.print('\tFree mangas\' scrambled images lead to quality loss. You should buy/rent them to download origin images.\n\tIf you still wants to download, please add "[bold]--descramble[/bold]"')
                    progress.remove_task(task_id)
                    progress.advance(total_task)
        
        asyncio.run(_internal())

    # TODO: How to get series infomation when only has a Title ID?
    #       Or how to decide that whether to use `read_free` or `jump_viewer`?
    # @app.command()
    # def download(tid: str = typer.Argument(help='renta.papy.co.jp/renta/sc/frm/item/123456/title/[blue bold]123456[/blue bold]')):
    #     if (result := re.search(r"renta.papy.co.jp/renta/sc/frm/item/[0-9]+/title/([0-9]+)/?", tid)):
    #         tid = result.group(1)
    #     else:
    #         tid = int(tid)
    
    app()
import base64
import gzip
import mimetypes
import shutil
import aiofiles
import asyncio
import re

from datetime import datetime, UTC
from dataclasses import dataclass
from lxml import etree
from pathlib import Path
from typing import Literal

from xor_engine import XorEngine

def sanitize_css(css_string: str):
    """
    Translated from Renta! Japan bundle.js in view_novel (New ePub Reader)
    """
    if not css_string:
        return ""
    
    sanitized = css_string

    # 1. 移除注释: /* ... */
    sanitized = re.sub(r'/\*[\s\S]*?\*/', '', sanitized)

    # 2. 移除 @ 规则 (media queries, keyframes, etc.)
    # 模拟 JS 的 /@[^;{]+(?:;|\s*\{(?:[^{}]*|\{[^{}]*\})*\})/gi
    at_rules_regex = re.compile(r'@[^;{]+(?:;|\s*\{(?:[^{}]*|\{[^{}]*\})*\})', re.IGNORECASE)
    sanitized = at_rules_regex.sub('', sanitized)

    # 3. 转换 body 选择器: "body .class" -> ".class"
    sanitized = re.sub(r'(^|[\s,])body\s+([a-z0-9-_.#\[:]+)\s*\{', r'\1\2 {', sanitized, flags=re.IGNORECASE)

    # 4. 处理 html/body 选择器，仅保留 border/outline 相关属性
    def html_body_replacer(match):
        selector = match.group(1)
        declarations = match.group(2)
        # 查找 border 或 outline 属性
        borders = re.findall(r'\b(?:border|outline)(?:-[a-z-]+)*\s*:[^;]+;', declarations, re.IGNORECASE)
        if borders:
            return f"{selector.strip()}{{{''.join(borders)}}}"
        return ""

    html_body_regex = re.compile(
        r'((?:^|[\s,])(?:html|body)(?:\.[a-z0-9-_]+|#[a-z0-9-_]+|:[a-z-]+)?)\s*\{([^}]*)\}',
        re.IGNORECASE
    )
    sanitized = html_body_regex.sub(html_body_replacer, sanitized)

    # 5. 移除根元素选择器 (svg, image, :not(svg))
    root_elements_regex = re.compile(
        r'(?:^|\s|,)(?::not\(svg\)|svg|image)(?:\.[a-z0-9-_]+|#[a-z0-9-_]+|:[a-z-]+)?(?:\s*[>+~]\s*|[^{,]*)\{[^}]*\}',
        re.IGNORECASE
    )
    sanitized = root_elements_regex.sub('', sanitized)

    # 6. 处理 -webkit-text-combine
    sanitized = re.sub(r'-webkit-text-combine\s*:[^;{}]*', 'text-combine-upright: all', sanitized, flags=re.IGNORECASE)

    # 7. 移除浏览器前缀属性 (-webkit-, -moz-, etc.)
    sanitized = re.sub(r'([{;])\s*-(?:webkit|epub|moz|ms|o)-[a-z-]+\s*:[^;{}]+;', r'\1', sanitized, flags=re.IGNORECASE)

    # 8. 将带有伪类的复杂选择器标记为未使用
    sanitized = re.sub(r'[a-z0-9-_.\s]+:[a-z0-9-_()]+(?=\s*\{)', '.unused-selector', sanitized, flags=re.IGNORECASE)

    # 9. 移除“有毒”属性（影响排版和定位的属性）
    toxic_properties = [
        "page-break-[a-z-]+",
        "writing-mode",
        "column-[a-z-]+",
        "hyphens",
        "float",
        "position",
        "clear",
        "overflow(?:-x|-y)?"
    ]
    toxic_regex = re.compile(f"({'|'.join(toxic_properties)}):[^;]+;", re.IGNORECASE)
    sanitized = toxic_regex.sub('', sanitized)

    # 10. 移除空规则块
    sanitized = re.sub(r'[^{}]+\{\s*\}', '', sanitized)
    
    # 11. 压缩多余空格
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()

    # 12. 布局属性清理
    layout_properties = [
        "margin(?:-top|-bottom|-left|-right)?",
        "padding(?:-top|-bottom|-left|-right)?",
        "max-width",
        "max-height",
    ]
    layout_regex = re.compile(rf"\b({'|'.join(layout_properties)})\s*:\s*[^;]+;", re.IGNORECASE)
    absolute_sizing_regex = re.compile(r"\b(width|height)\s*:\s*([0-9.]+(px|%|cm|mm|in|pt|pc)|auto)\s*;", re.IGNORECASE)

    def rule_block_replacer(match):
        selector = match.group(1)
        body = match.group(2)
        
        # 如果包含 'gaiji' (外字)，保留原始规则
        if re.search(r'gaiji', selector, re.IGNORECASE):
            return match.group(0)
            
        has_negative_text_indent = bool(re.search(r'\btext-indent\s*:\s*-', body))
        
        def layout_sub_replacer(m2):
            prop = m2.group(1).lower()
            # 如果有负向文本缩进，保留 padding-left 或 padding-top
            if has_negative_text_indent and prop in ['padding-left', 'padding-top']:
                return m2.group(0)
            return ""

        cleaned_body = layout_regex.sub(layout_sub_replacer, body)
        cleaned_body = absolute_sizing_regex.sub('', cleaned_body)
        return f"{selector}{{{cleaned_body}}}"

    sanitized = re.sub(r'([^{}]+)\{([^}]*)\}', rule_block_replacer, sanitized)

    # 13. 追加重置样式
    reset_tags = "p, div, h1, h2, h3, h4, h5, h6, ol, ul, li, blockquote"
    sanitized += f" {reset_tags} {{ margin-top: 0 !important; }}"
    sanitized += " ol, ul { padding-left: 0 !important; }"

    return sanitized

class ViewNovelDecryptor:
    xor = XorEngine()

    @staticmethod
    def decrypt_content(content: str, key: str):
        '''
        Decrypt content data of new view_novel (previous view_epub2)

        XOR encrypted GZip data
        
        :param content: base64 encoded content data
        :type content: str

        :param key: USC1 (Client Key) in cookies
        :type key: str
        '''
        b_content = base64.b64decode(content)
        b_key = key.encode()

        compressed = ViewNovelDecryptor.xor.xor_engine(b_content, b_key, 0)

        return gzip.decompress(compressed)

class XMLTool:
    @staticmethod
    def remove_attr(tree: etree, target_attr: str):
        for el in tree.xpath(f'//*[@{target_attr}]'):
            el.attrib.pop(target_attr, None)

    @staticmethod
    def generete_xhtml(
        content: str, 
        title: str, 
        styles: list[str] | None = None, 
        remove_attrs: list[str] | None = None,
        desired_reading_direction: Literal['horizontal', 'vertical'] | None = None
    ) -> str:
        NSMAP = {
            None: "http://www.w3.org/1999/xhtml",
            "epub": "http://www.idpf.org/2007/ops"
        }
        
        root = etree.Element("html", nsmap=NSMAP)
        head = etree.SubElement(root, "head")
        etree.SubElement(head, "meta", charset="utf-8")
        etree.SubElement(head, "title").text = title

        base_css = etree.SubElement(
            head, 
            "link", 
            rel="stylesheet", 
            type="text/css"
        )
        base_css.text = "*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}"

        if styles:
            for css_name in styles:
                etree.SubElement(
                    head, 
                    "link", 
                    rel="stylesheet", 
                    href=f"../style/{css_name}",
                    type="text/css"
                )
        
        body = etree.SubElement(root, "body")

        if desired_reading_direction:
            body = etree.SubElement(body, "div", **{
                "style": 
                    f"writing-mode: {'vertical-rl' if desired_reading_direction == 'vertical' else 'horizontal-tb'}; "
                    "display: flex; justify-content: center; align-items: center;",
                "class": "vrtl" if desired_reading_direction == 'vertical' else "hltr"
            })
        
        wrapped_xml = f'''<div xmlns:epub="{NSMAP['epub']}">{content.strip()}</div>'''
        wrapped_fragment = etree.fromstring(wrapped_xml)
        fragment = wrapped_fragment[0]
        if remove_attrs:
            for attr in remove_attrs:
                XMLTool.remove_attr(fragment, attr)
        body.append(fragment)
        
        return etree.tostring(
            root, 
            encoding="utf-8", 
            pretty_print=True, 
            method="xml", 
            doctype="<!DOCTYPE html>",
            xml_declaration=True
        ).decode()

MIME_MAP = {
    '.xhtml': 'application/xhtml+xml',
    '.css': 'text/css',
    '.otf': 'application/x-font-opentype',
    '.ttf': 'application/x-font-truetype',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
}

def get_mimetype(filename: str) -> str:
    ext = "." + filename.split('.')[-1].lower()
    return MIME_MAP.get(ext, mimetypes.guess_type(filename)[0] or 'application/octet-stream')

@dataclass
class ViewNovelData:
    id: str
    title: str
    language: str
    creators: list[str]
    spine_direction: str
    nav: dict[str, dict[str, str | int]]
    images: list[str]

@dataclass
class ViewNovelSection:
    content: str
    anchors: list[str]
    start_index: int
    end_index: int
    filepath: str
    desired_reading_direction: str | None = None
    spread: str | None = None

    decrypted: bool = False

    def generete_xhtml(self, title: str, styles: list[str] | None = None, key: str | None = None):
        if not self.decrypted:
            if not key:
                raise RuntimeError("Must decrypt section.data first")
            else:
                self.content = ViewNovelDecryptor.decrypt_content(self.content, key)
                self.decrypted = True
        # return render_page_to_xhtml(self.content, sanitize_css(''.join(styles)), self.desired_reading_direction is None, self.desired_reading_direction)
        return XMLTool.generete_xhtml(self.content, title, styles, ("data-index", ), self.desired_reading_direction)

class ViewNovelContents:
    sections: list[ViewNovelSection]
    css: list[str]

    decrypted: bool = False

    def __init__(self, sections: list[dict], css: list[str]):
        self.sections = []
        for section in sections:
            self.sections.append(ViewNovelSection(**section))
        self.css = css

    def decrypt_sections(self, key: str):
        for section in self.sections:
            if section.decrypted: continue
            section.content = ViewNovelDecryptor.decrypt_content(section.content, key).decode()
            section.decrypted = True
        self.decrypted = True

    async def decrypt_sections_async(self, key: str):
        async def _decrypt_section(idx: int, content: str):
            return idx, (await asyncio.to_thread(
                ViewNovelDecryptor.decrypt_content, content, key
            )).decode()
        
        tasks = [
            asyncio.create_task(_decrypt_section(i, section.content))
            for i, section in enumerate(self.sections) if not section.decrypted
        ]
        for t in asyncio.as_completed(tasks):
            i, decrypted = await t
            self.sections[i].decrypted = True
            self.sections[i].content = decrypted
        
        self.decrypted = True

class ViewNovelEpubBuilder:
    @staticmethod
    def generate_opf(nav_data: ViewNovelData, contents: ViewNovelContents) -> str:
    # 定义命名空间
        NS_OPF = "http://www.idpf.org/2007/opf"
        NS_DC = "http://purl.org/dc/elements/1.1/"
        
        nsmap = {None: NS_OPF, 'dc': NS_DC}
        
        # 1. Root element
        root = etree.Element(f"{{{NS_OPF}}}package", 
                            nsmap=nsmap, 
                            version="3.0", 
                            unique_identifier="pub-id")

        # 2. Metadata
        metadata = etree.SubElement(root, f"{{{NS_OPF}}}metadata")
        # Identifier
        dc_id = etree.SubElement(metadata, f"{{{NS_DC}}}identifier", id="pub-id")
        dc_id.text = nav_data.id
        # Title
        dc_title = etree.SubElement(metadata, f"{{{NS_DC}}}title")
        dc_title.text = nav_data.title
        # Language
        dc_lang = etree.SubElement(metadata, f"{{{NS_DC}}}language")
        dc_lang.text = nav_data.language
        # Creators
        for idx, creator in enumerate(nav_data.creators):
            dc_creator = etree.SubElement(metadata, f"{{{NS_DC}}}creator", id=f"creator{idx + 1:>02d}")
            dc_creator.text = creator
        # Modification Date
        meta_date = etree.SubElement(metadata, f"{{{NS_OPF}}}meta", property="dcterms:modified")
        meta_date.text = datetime.now(UTC).isoformat()

        # 3. Manifest
        manifest = etree.SubElement(root, f"{{{NS_OPF}}}manifest")
        
        # 强制包含 nav.xhtml
        etree.SubElement(manifest, f"{{{NS_OPF}}}item", 
                        id="nav", href="nav.xhtml", 
                        properties="nav", **{"media-type": "application/xhtml+xml"})

        # 遍历内容文件 (XHTML)
        added_files = set()
        for section in contents.sections:
            file_path = section.filepath
            if file_path not in added_files:
                item_id = file_path.replace('.', '_')
                etree.SubElement(manifest, f"{{{NS_OPF}}}item", 
                                id=item_id, href=f"xhtml/{section.filepath}", 
                                **{"media-type": get_mimetype(file_path)})
                added_files.add(file_path)

        # 遍历图片
        for idx, img in enumerate(nav_data.images):
            img_id = img.replace('.', '_')
            attrs = {"media-type": get_mimetype(img)}
            if idx == 0:
                img_id = "cover"
                attrs["properties"] = "cover-image"
            etree.SubElement(manifest, f"{{{NS_OPF}}}item", 
                            id=img_id, href=f"image/{img}", 
                            **attrs)
            
        css_id = f"style_css"
        attrs = {"media-type": "text/css"}
        etree.SubElement(manifest, f"{{{NS_OPF}}}item", 
                        id=css_id, href=f"style/style.css", 
                        **attrs)

        # 4. Spine
        spine = etree.SubElement(root, f"{{{NS_OPF}}}spine", **{"page-progression-direction": "rtl"})
        
        for section in contents.sections:
            item_ref_id = section.filepath.replace('.', '_')
            etree.SubElement(spine, f"{{{NS_OPF}}}itemref", idref=item_ref_id)

        return etree.tostring(
            root, pretty_print=True, 
            encoding='utf-8', xml_declaration=True, doctype="<!DOCTYPE html>"
        ).decode()

    @staticmethod
    def generate_toc(nav_data: ViewNovelData):
        NS_XHTML = "http://www.w3.org/1999/xhtml"
        NS_EPUB = "http://www.idpf.org/2007/ops"
        
        nsmap = {None: NS_XHTML, 'epub': NS_EPUB}
        
        root = etree.Element(f"{{{NS_XHTML}}}html", nsmap=nsmap)
        
        # Head
        head = etree.SubElement(root, f"{{{NS_XHTML}}}head")
        title = etree.SubElement(head, f"{{{NS_XHTML}}}title")
        title.text = nav_data.title
        
        # Body
        body = etree.SubElement(root, f"{{{NS_XHTML}}}body")
        nav = etree.SubElement(body, f"{{{NS_XHTML}}}nav", 
                            **{f"{{{NS_EPUB}}}type": "toc"}, id="toc")
        
        h1 = etree.SubElement(nav, f"{{{NS_XHTML}}}h1")
        h1.text = "Table of Contents"
        
        ol = etree.SubElement(nav, f"{{{NS_XHTML}}}ol")
        
        # 生成目录列表
        for title_text, info in nav_data.nav.items():
            li = etree.SubElement(ol, f"{{{NS_XHTML}}}li")
            a = etree.SubElement(li, f"{{{NS_XHTML}}}a", href=f"xhtml/{info['file']}")
            a.text = title_text
            
        return etree.tostring(
            root, pretty_print=True, 
            encoding='utf-8', xml_declaration=True, doctype="<!DOCTYPE html>"
        ).decode()
    
    @staticmethod
    async def build(data_json: dict, contents_json: dict, key: str, target_dir: Path) -> dict[str, Path]:
        if (build_dir := target_dir / 'build').exists():
            shutil.rmtree(build_dir)

        OEBPS_dir = build_dir / 'OEBPS'
        OEBPS_dir.mkdir(parents=True, exist_ok=True)

        images_dir = OEBPS_dir / 'image'
        images_dir.mkdir(parents=True, exist_ok=True)

        xhtml_dir = OEBPS_dir / 'xhtml'
        xhtml_dir.mkdir(parents=True, exist_ok=True)

        style_dir = OEBPS_dir/ 'style'
        style_dir.mkdir(parents=True, exist_ok=True)

        data = ViewNovelData(**data_json)
        contents = ViewNovelContents(**contents_json)

        await contents.decrypt_sections_async(key)

        async def write_file(filepath: Path, content: str):
            filepath.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(filepath, mode='w', encoding='utf-8') as f:
                await f.write(content)
        
        title_map = {body['file']: title for title, body in data.nav.items()}
        styles = [f"style.css"]

        tasks = [
            asyncio.create_task(
                write_file(OEBPS_dir / "standard.opf", ViewNovelEpubBuilder.generate_opf(data, contents))
            ),
            asyncio.create_task(
                write_file(OEBPS_dir / "nav.xhtml", ViewNovelEpubBuilder.generate_toc(data))
            )
        ]
        tasks.extend(
            asyncio.create_task(
                write_file(xhtml_dir / section.filepath, section.generete_xhtml(
                    title_map.get(section.filepath, ""), 
                    (styles if section.desired_reading_direction else None)
                ))
            )
            for section in contents.sections
        )
        tasks.append(
            asyncio.create_task(
                write_file(style_dir / f"style.css", sanitize_css(''.join(contents.css)))
            )
        )

        await asyncio.gather(*tasks)

        meta_inf_dir = build_dir / "META-INF"
        meta_inf_dir.mkdir(parents=True, exist_ok=True)
        await write_file(
            meta_inf_dir / "container.xml", 
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles>'
            '<rootfile full-path="OEBPS/standard.opf" media-type="application/oebps-package+xml"/>'
            '</rootfiles>'
            '</container>'
        )

        return {
            img: images_dir / img
            for img in data.images
        }
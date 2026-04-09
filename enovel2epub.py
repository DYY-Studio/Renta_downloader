import aiofiles
import uuid
import shutil
from bs4 import BeautifulSoup
from pathlib import Path

CSS_CONTENT = """
:root {
    --bg-color: rgba(246,245,255,1);
    --text-color: #4c3a35;
    --name-color: #4c3a35;
}


@media (prefers-color-scheme: dark) {
    :root {
        --bg-color: #2c2c2e;
        --text-color: #d1d1d6;
        --name-color: #0a84ff;
    }
}

body { font-family: "serif", "Hiragino Mincho ProN", serif; margin: 5%; color: var(--name-color); }
.scroll_win { width: 100%; border-collapse: collapse; margin-bottom: 15px; color: var(--text-color); background-color: var(--bg-color); }
.face_g { width: 80px; height: 80px; background-size: cover; background-repeat: no-repeat; }
.name { font-size: 90%; font-weight: bold; display: block; margin-bottom: 5px; color: var(--name-color); }
.str_text { display: block; text-align: justify; line-height: 1.6; }
.narrative { line-height: 1.8; margin: 1em 0; text-align: justify; color: var(--text-color); background-color: var(--bg-color);}
.scroll_g_win { width: 100%; text-align: center; margin: 15px 0; }
.illustration { max-width: 100%; height: auto; }
ruby rt { font-size: 0.6em; }
"""

class ENovelEpubBuilder:
    def __init__(self, title: str, author: str):
        self.title = title
        self.author = author
        self.book_id = str(uuid.uuid4())
        self.chapters = []
        self.images = set()

    def create_chapter_xhtml(self, chapter_data: dict, index: int):
        """利用BeautifulSoup构建章节页面"""
        soup = BeautifulSoup('<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head></head><body></body></html>', "xml")
        
        # Head
        title_tag = soup.new_tag("title")
        title_tag.string = chapter_data['title']
        soup.head.append(title_tag)
        link_tag = soup.new_tag("link", rel="stylesheet", href="style.css", type="text/css")
        soup.head.append(link_tag)

        for msg in chapter_data['message']:
            # 处理插画/大图 (thum 节点)
            if 'ctr' in msg and msg.get('thum') == 1:
                img_name = msg['ctr']
                self.images.add(img_name)
                div = soup.new_tag("div", attrs={"class": "scroll_g_win"})
                img = soup.new_tag("img", src=f"images/{img_name}", attrs={"class": "illustration"})
                div.append(img)
                soup.body.append(div)
            
            # 处理对话节点 (含有 name 和 ctr)
            elif 'name' in msg and msg['name'] != "":
                img_name = msg.get('ctr', '')
                if img_name: self.images.add(img_name)
                
                table = soup.new_tag("table", attrs={"class": "scroll_win"})
                tr = soup.new_tag("tr")
                
                if img_name:
                    td_face = soup.new_tag("td", attrs={"width": "80"})
                    face_div = soup.new_tag("div", attrs={"class": "face_g"})
                    face_div['style'] = f"background-image:url('images/{img_name}')"
                    td_face.append(face_div)
                    tr.append(td_face)
                
                td_text = soup.new_tag("td", valign="top")
                p = soup.new_tag("p", attrs={"class": "str_text"})
                
                name_span = soup.new_tag("span", attrs={"class": "name"})
                name_span.string = msg['name']
                p.append(name_span)
                
                text_content = BeautifulSoup(msg.get('str', ''), "html.parser")
                p.append(text_content)
                
                td_text.append(p)
                tr.append(td_text)
                table.append(tr)
                soup.body.append(table)

            # 处理纯文本/旁白
            elif 'str' in msg:
                p = soup.new_tag("p", attrs={"class": "narrative"})
                text_content = BeautifulSoup(msg.get('str', ''), "html.parser")
                p.append(text_content)
                soup.body.append(p)

        return soup.prettify()

    async def build(self, json_data: dict, target_dir: Path) -> dict[str, Path]:
        if (build_dir := target_dir / 'build').exists():
            shutil.rmtree(build_dir)
        images_dir = target_dir / 'build/OEBPS/images'
        images_dir.mkdir(parents=True, exist_ok=True)
        
        manifest_items = ""
        spine_items = ""
        for i, ch_data in enumerate(json_data):
            filename = f"chapter_{i}.xhtml"
            content = self.create_chapter_xhtml(ch_data, i)
            async with aiofiles.open(target_dir / f"build/OEBPS/{filename}", "w", encoding="utf-8") as f:
                await f.write(content)
            
            manifest_items += f'<item id="ch{i}" href="{filename}" media-type="application/xhtml+xml" />\n'
            spine_items += f'<itemref idref="ch{i}" />\n'
            self.chapters.append((filename, ch_data['title']))

        async with aiofiles.open(target_dir / "build/OEBPS/style.css", "w", encoding="utf-8") as f:
            await f.write(CSS_CONTENT)

        img_manifest = ""
        for img in self.images:
            ext = img.split('.')[-1]
            mtype = "image/jpeg" if ext in ['jpg', 'jpeg'] else "image/png"
            img_manifest += f'<item id="{img.replace(".","_")}" href="images/{img}" media-type="{mtype}" />\n'

        opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">{self.book_id}</dc:identifier>
    <dc:title>{self.title}</dc:title>
    <dc:creator>{self.author}</dc:creator>
    <dc:language>ja</dc:language>
    <meta name="cover" content="{json_data[0]['message'][0]['ctr'].replace('.', '_')}" />
  </metadata>
  <manifest>
    <item id="style" href="style.css" media-type="text/css" />
    {manifest_items}
    {img_manifest}
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />
  </manifest>
  <spine>
    {spine_items}
  </spine>
</package>"""
        async with aiofiles.open(target_dir / "build/OEBPS/content.opf", "w", encoding="utf-8") as f:
            await f.write(opf)

        nav_links = "".join([f'<li><a href="{f}">{t}</a></li>' for f, t in self.chapters])
        nav = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>

<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title></title></head>
  <body>
    <nav epub:type="toc">
      <h1>Table of Contents</h1>
      <ol>{nav_links}</ol>
    </nav>
  </body>
</html>"""
        async with aiofiles.open(target_dir / "build/OEBPS/nav.xhtml", "w", encoding="utf-8") as f:
            await f.write(nav)

        (target_dir / 'build/META-INF').mkdir(exist_ok=True, parents=True)
        async with aiofiles.open(target_dir / "build/META-INF/container.xml", "w", encoding="utf-8") as f:
            await f.write('<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')

        return {img: images_dir / img for img in self.images}

from dataclasses import dataclass, asdict
from typing import Optional, Literal
import xml.etree.ElementTree as ET
from xml.dom import minidom

ComicInfoManga = Literal['Yes', 'No', 'Unknown', 'YesAndRightToLeft']

@dataclass
class ComicInfoMetadata:
    Title: Optional[str] = None
    Series: Optional[str] = None
    Number: Optional[str] = None
    Count: Optional[int] = None
    Volume: Optional[int] = None
    Summary: Optional[str] = None
    Notes: Optional[str] = None
    
    Writer: Optional[str] = None
    Penciller: Optional[str] = None
    Inker: Optional[str] = None
    Colorist: Optional[str] = None
    Letterer: Optional[str] = None
    CoverArtist: Optional[str] = None
    Editor: Optional[str] = None
    
    Publisher: Optional[str] = None
    Genre: Optional[str] = None
    Web: Optional[str] = None
    LanguageISO: Optional[str] = None
    Year: Optional[int] = None
    Month: Optional[int] = None
    Day: Optional[int] = None
    
    PageCount: Optional[int] = None
    Manga: Optional[ComicInfoManga] = None
    Characters: Optional[str] = None
    Teams: Optional[str] = None
    ScanInformation: Optional[str] = None

    def generate_xml(self):
        root = ET.Element("ComicInfo", {
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"
        })

        data_dict = {k: v for k, v in asdict(self).items() if v is not None}

        for key, value in data_dict.items():
            child = ET.SubElement(root, key)
            child.text = str(value)

        xml_str = ET.tostring(root, encoding='utf-8')
        return minidom.parseString(xml_str).toprettyxml(indent="  ", encoding="utf-8")
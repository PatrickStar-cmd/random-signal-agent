"""A tiny PPTX writer for simple course presentation slides."""

from __future__ import annotations

import html
import zipfile
from pathlib import Path


SLIDE_W = 13_333_500
SLIDE_H = 7_500_000


def _xml_escape(text: str) -> str:
    return html.escape(text, quote=True)


def _text_box(
    shape_id: int,
    name: str,
    x: int,
    y: int,
    w: int,
    h: int,
    lines: list[str],
    font_size: int = 2400,
    bold: bool = False,
    color: str = "172033",
) -> str:
    paragraphs = []
    for line in lines:
        paragraphs.append(
            "<a:p>"
            "<a:r>"
            f"<a:rPr lang=\"zh-CN\" sz=\"{font_size}\"{' b=\"1\"' if bold else ''}>"
            f"<a:solidFill><a:srgbClr val=\"{color}\"/></a:solidFill>"
            "</a:rPr>"
            f"<a:t>{_xml_escape(line)}</a:t>"
            "</a:r>"
            "</a:p>"
        )
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{shape_id}" name="{_xml_escape(name)}"/>
    <p:cNvSpPr txBox="1"/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
    <a:noFill/>
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square"/>
    <a:lstStyle/>
    {''.join(paragraphs)}
  </p:txBody>
</p:sp>
""".strip()


def _rect(
    shape_id: int,
    name: str,
    x: int,
    y: int,
    w: int,
    h: int,
    fill: str,
    line: str = "FFFFFF",
) -> str:
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{shape_id}" name="{_xml_escape(name)}"/>
    <p:cNvSpPr/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
    <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
    <a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>
    <a:ln><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>
  </p:spPr>
</p:sp>
""".strip()


def _slide_xml(shapes: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="F6F8FB"/></a:solidFill></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      {shapes}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""


def _content_types(slide_count: int) -> str:
    overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  {overrides}
</Types>
"""


def _root_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def _presentation_xml(slide_count: int) -> str:
    slide_ids = "\n".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i}"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{slide_count + 1}"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
"""


def _presentation_rels(slide_count: int) -> str:
    rels = []
    for i in range(1, slide_count + 1):
        rels.append(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{slide_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
    )
    rels.append(
        f'<Relationship Id="rId{slide_count + 2}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="theme/theme1.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )


def _slide_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>
"""


def _slide_master() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>
"""


def _slide_master_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
"""


def _slide_layout() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
"""


def _theme() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="RandomSignalAgent">
  <a:themeElements>
    <a:clrScheme name="Agent">
      <a:dk1><a:srgbClr val="172033"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="0F172A"/></a:dk2><a:lt2><a:srgbClr val="F6F8FB"/></a:lt2>
      <a:accent1><a:srgbClr val="0F766E"/></a:accent1><a:accent2><a:srgbClr val="2563EB"/></a:accent2>
      <a:accent3><a:srgbClr val="DC2626"/></a:accent3><a:accent4><a:srgbClr val="7C3AED"/></a:accent4>
      <a:accent5><a:srgbClr val="F59E0B"/></a:accent5><a:accent6><a:srgbClr val="64748B"/></a:accent6>
      <a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Microsoft YaHei"><a:majorFont><a:latin typeface="Microsoft YaHei"/></a:majorFont><a:minorFont><a:latin typeface="Microsoft YaHei"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="Default"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>
  </a:themeElements>
</a:theme>
"""


def _core_props() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>随机信号智能体项目汇报</dc:title>
  <dc:creator>Random Signal Agent</dc:creator>
</cp:coreProperties>
"""


def _app_props(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex PPTX Writer</Application>
  <PresentationFormat>宽屏</PresentationFormat>
  <Slides>{slide_count}</Slides>
</Properties>
"""


def build_slides(result: dict) -> list[str]:
    """Create slide XML payloads from analysis result."""
    summary = result["summary"]
    quality = summary["quality"]
    freq = summary["frequency_features"]
    decision = result["decision"]

    slides: list[str] = []
    slides.append(
        _slide_xml(
            _rect(2, "TopBar", 0, 0, SLIDE_W, 700_000, "0F172A")
            + _text_box(3, "Title", 620_000, 1_150_000, 9_800_000, 1_000_000, ["随机信号智能体项目"], 4400, True)
            + _text_box(4, "SubTitle", 650_000, 2_170_000, 10_500_000, 900_000, ["感知采集、噪声预处理、时频域分析与决策控制闭环"], 2600, False, "334155")
            + _rect(5, "Accent", 650_000, 3_400_000, 4_800_000, 120_000, "0F766E")
            + _text_box(6, "Footer", 650_000, 4_000_000, 10_800_000, 1_300_000, ["课程知识点：随机过程统计量、自相关、功率谱、谱熵、SNR"], 2300, False, "475569")
        )
    )
    slides.append(
        _slide_xml(
            _text_box(2, "Title", 500_000, 420_000, 10_000_000, 600_000, ["任务要求与项目对应"], 3400, True)
            + _text_box(
                3,
                "Bullets",
                720_000,
                1_420_000,
                11_600_000,
                4_800_000,
                [
                    "以智能体为核心载体：四个专职智能体串联成分析闭环",
                    "随机信号实时采集：模拟传感器窗口输出带噪随机过程",
                    "噪声预处理：MAD 异常点检测、局部中值修复、滑动平均",
                    "时域与频域特征：统计量、自相关、FFT 功率谱、谱熵",
                    "项目交付：代码、演示页面、设计报告、PPT 汇报",
                ],
                2400,
            )
        )
    )
    slides.append(
        _slide_xml(
            _text_box(2, "Title", 500_000, 420_000, 10_000_000, 600_000, ["多智能体架构"], 3400, True)
            + _rect(3, "A1", 700_000, 1_600_000, 2_400_000, 900_000, "E0F2FE", "2563EB")
            + _rect(4, "A2", 3_500_000, 1_600_000, 2_400_000, 900_000, "DCFCE7", "0F766E")
            + _rect(5, "A3", 6_300_000, 1_600_000, 2_400_000, 900_000, "FEF3C7", "F59E0B")
            + _rect(6, "A4", 9_100_000, 1_600_000, 2_400_000, 900_000, "FEE2E2", "DC2626")
            + _text_box(7, "T1", 900_000, 1_830_000, 2_000_000, 400_000, ["SensorAgent"], 2200, True, "1E3A8A")
            + _text_box(8, "T2", 3_700_000, 1_830_000, 2_000_000, 400_000, ["PreprocessAgent"], 2100, True, "14532D")
            + _text_box(9, "T3", 6_540_000, 1_830_000, 2_000_000, 400_000, ["FeatureAgent"], 2200, True, "92400E")
            + _text_box(10, "T4", 9_310_000, 1_830_000, 2_000_000, 400_000, ["DecisionAgent"], 2200, True, "991B1B")
            + _text_box(
                11,
                "Explain",
                850_000,
                3_100_000,
                11_300_000,
                2_100_000,
                [
                    "编排器 RandomSignalOrchestrator 负责共享状态传递和结果汇总。",
                    "各智能体只承担单一职责，便于调试、扩展和课堂解释。",
                    "与参考项目类似，采用“任务拆分、专职智能体协作、统一报告输出”的模式。",
                ],
                2300,
            )
        )
    )
    slides.append(
        _slide_xml(
            _text_box(2, "Title", 500_000, 420_000, 10_000_000, 600_000, ["核心实验结果"], 3400, True)
            + _text_box(
                3,
                "Metrics",
                850_000,
                1_350_000,
                11_500_000,
                4_700_000,
                [
                    f"状态判定：{decision['status']}，控制策略：{decision['filter_level']}",
                    f"原始 SNR：{quality['raw_snr_db']:.2f} dB，预处理后 SNR：{quality['processed_snr_db']:.2f} dB",
                    f"SNR 提升：{quality['snr_improvement_db']:.2f} dB，异常点率：{quality['anomaly_rate'] * 100:.2f}%",
                    f"主频：{freq['dominant_frequency_hz']:.2f} Hz，谱熵：{freq['spectral_entropy']:.3f}",
                    f"下一步建议窗口：{decision['control_parameters']['next_smoothing_window']} 点",
                ],
                2500,
            )
        )
    )
    action_lines = decision["recommended_actions"][:5]
    slides.append(
        _slide_xml(
            _text_box(2, "Title", 500_000, 420_000, 10_000_000, 600_000, ["总结与扩展方向"], 3400, True)
            + _text_box(
                3,
                "Actions",
                820_000,
                1_300_000,
                11_600_000,
                3_700_000,
                ["本次决策建议："] + [f"- {line}" for line in action_lines],
                2250,
            )
            + _text_box(
                4,
                "Future",
                820_000,
                5_300_000,
                11_200_000,
                900_000,
                ["可扩展方向：接入真实传感器、引入卡尔曼滤波/AR 模型预测、增加 LLM 解释层。"],
                2200,
                False,
                "475569",
            )
        )
    )
    return slides


def write_pptx(result: dict, output_path: Path) -> None:
    """Write a PowerPoint-compatible PPTX file."""
    slides = build_slides(result)
    slide_count = len(slides)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as pptx:
        pptx.writestr("[Content_Types].xml", _content_types(slide_count))
        pptx.writestr("_rels/.rels", _root_rels())
        pptx.writestr("ppt/presentation.xml", _presentation_xml(slide_count))
        pptx.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(slide_count))
        pptx.writestr("ppt/slideMasters/slideMaster1.xml", _slide_master())
        pptx.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _slide_master_rels())
        pptx.writestr("ppt/slideLayouts/slideLayout1.xml", _slide_layout())
        pptx.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _slide_rels())
        pptx.writestr("ppt/theme/theme1.xml", _theme())
        pptx.writestr("docProps/core.xml", _core_props())
        pptx.writestr("docProps/app.xml", _app_props(slide_count))
        for idx, slide_xml in enumerate(slides, start=1):
            pptx.writestr(f"ppt/slides/slide{idx}.xml", slide_xml)
            pptx.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", _slide_rels())

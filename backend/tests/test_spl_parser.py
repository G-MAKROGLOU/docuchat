"""SplXmlParser on a small SPL document with the shapes DailyMed uses."""

import pytest

from app.domain.entities import LabelNode
from app.infrastructure.spl_parser import SplXmlParser

SPL = b"""<?xml version="1.0" encoding="UTF-8"?>
<document xmlns="urn:hl7-org:v3">
 <component><structuredBody>
  <component><section>
   <code code="48780-1" codeSystem="2.16.840.1.113883.6.1"/>
   <title>These highlights do not include all the information</title>
   <text><paragraph>Highlights text.</paragraph></text>
  </section></component>
  <component><section ID="s1">
   <code code="34068-7" codeSystem="2.16.840.1.113883.6.1"/>
   <title>2  DOSAGE AND <content styleCode="bold">ADMINISTRATION</content></title>
   <component><section>
    <code code="42229-5"/>
    <title>2.1 Adults</title>
    <text>
     <paragraph>Take <content styleCode="italics">10 mg</content>
       once daily.</paragraph>
     <list><item>With food.</item><item>Without food.</item></list>
     <table><caption>Table 1. Doses</caption>
      <thead><tr><th>Group</th><th>Dose</th></tr></thead>
      <tbody><tr><td>Adults</td><td><paragraph>10 mg</paragraph></td></tr>
       <tr><td/><td> </td></tr></tbody>
     </table>
     <paragraph>Line one<br/>line two.</paragraph>
    </text>
   </section></component>
  </section></component>
 </structuredBody></component>
</document>
"""


def test_sections_keep_code_title_text_and_children() -> None:
    nodes = SplXmlParser().sections(SPL)

    assert [n.code for n in nodes] == ["48780-1", "34068-7"]
    dosage = nodes[1]
    assert (dosage.title, dosage.text) == ("2 DOSAGE AND ADMINISTRATION", "")
    assert dosage.children == (
        LabelNode(
            code="42229-5",
            title="2.1 Adults",
            text=(
                "Take 10 mg once daily.\n- With food.\n- Without food.\nTable 1. Doses\n"
                "Group | Dose\nAdults | 10 mg\nLine one\nline two."
            ),
            children=(),
        ),
    )


def test_a_list_item_keeps_one_marker_and_drops_its_bullet_caption() -> None:
    spl = (
        b'<document xmlns="urn:hl7-org:v3"><component><structuredBody><component><section>'
        b'<code code="34066-1"/><title>WARNING</title><text><list>'
        b"<item><caption>\xe2\x80\xa2</caption><paragraph>Risk of heart attack.</paragraph></item>"
        b"<item><caption>o</caption>Risk of stroke.</item>"
        b"</list></text></section></component></structuredBody></component></document>"
    )

    assert SplXmlParser().sections(spl)[0].text == "- Risk of heart attack.\n- Risk of stroke."


def test_a_document_without_a_structured_body_raises() -> None:
    with pytest.raises(ValueError, match="structured body"):
        SplXmlParser().sections(b'<document xmlns="urn:hl7-org:v3"/>')

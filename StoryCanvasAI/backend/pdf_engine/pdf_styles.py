from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor

styles = getSampleStyleSheet()


TITLE_STYLE = styles["Heading1"]
TITLE_STYLE.alignment = TA_CENTER
TITLE_STYLE.fontSize = 26
TITLE_STYLE.spaceAfter = 20


SUBTITLE_STYLE = styles["Heading2"]
SUBTITLE_STYLE.alignment = TA_CENTER
SUBTITLE_STYLE.fontSize = 16
SUBTITLE_STYLE.textColor = HexColor("#555555")
SUBTITLE_STYLE.spaceAfter = 30


HEADING_STYLE = styles["Heading2"]
HEADING_STYLE.spaceAfter = 15


BODY_STYLE = styles["BodyText"]
BODY_STYLE.fontSize = 13
BODY_STYLE.leading = 20
BODY_STYLE.alignment = TA_JUSTIFY


FOOTER_STYLE = styles["Normal"]
FOOTER_STYLE.alignment = TA_CENTER
FOOTER_STYLE.fontSize = 9
FOOTER_STYLE.textColor = HexColor("#777777")
"""Private movie protocol adapter. Commons APIs use ordinary JSON."""
import base64
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.padding import PKCS7

DAS = [280, 200, 150, 133, 120]
ARR = [50, 35, 17, 7, 0]
PRIVATE_FIELDS = {"SessionId", "SessionToken", "GameToken", "Ip", "Timestamp", "LoginId"}
CALLS = {"LoginOpenWebRQ", "GameInitSprintRQ", "GameStartRQ", "UpdateUserOpenWebSettingsRQ",
         "CreateSprintGameRecordRQ", "GameCompletedRQ"}

def encrypt(text: str, key: bytes) -> str:
    padder = PKCS7(64).padder()
    data = padder.update(text.encode()) + padder.finalize()
    cipher = Cipher(Blowfish(key), modes.ECB()).encryptor()
    return base64.b64encode(cipher.update(data) + cipher.finalize()).decode()

def decrypt(text: str, key: bytes) -> str:
    data = base64.b64decode(text, validate=True)
    cipher = Cipher(Blowfish(key), modes.ECB()).decryptor()
    data = cipher.update(data) + cipher.finalize()
    unpadder = PKCS7(64).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode()

def parse_xml(text: str) -> ET.Element:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("Unsupported XML declaration")
    return ET.fromstring(text)

def decode(body: bytes, key: bytes) -> ET.Element:
    text = body.decode()
    if text.startswith("encryptedXml="):
        text = decrypt(unquote(text.removeprefix("encryptedXml=").strip()), key)
    elif text.startswith("xml="):
        text = text.removeprefix("xml=")
    else:
        raise ValueError("Unsupported game request")
    root = parse_xml(text)
    if root.tag not in CALLS:
        raise ValueError("Unsupported game operation")
    return root

def set_handling(xml: str, settings: dict) -> str:
    root = parse_xml(xml)
    for name, value in (("CurDas", 9000 + DAS.index(settings["das_ms"])),
                        ("CurArr", 9006 + ARR.index(settings["arr_ms"]))):
        element = root.find(name)
        if element is None:
            element = ET.SubElement(root, name)
        element.text = str(value)
    return ET.tostring(root, encoding="unicode")

def response(command: str, body: str = "") -> str:
    return f'<?xml version="1.0"?><{command[:-2]}RS><Success>true</Success>{body}</{command[:-2]}RS>'

def metrics_and_record(root: ET.Element) -> tuple[dict, str]:
    for parent in root.iter():
        for child in list(parent):
            if child.tag in PRIVATE_FIELDS:
                parent.remove(child)
    names = {"Score": "score", "TimeInMS": "elapsed_ms", "LinesCleared": "lines",
             "Tetriminos": "pieces", "Notris": "four_line_clears", "Combos": "combos",
             "MaxCombos": "max_combo", "Singles": "singles", "Doubles": "doubles", "Triples": "triples"}
    metrics = {names[child.tag]: int(child.text) for child in root.iter()
               if child.tag in names and child.text and child.text.isdigit() and len(child.text) <= 16}
    return metrics, ET.tostring(root, encoding="unicode")

def handle(root: ET.Element, session: dict, store, key: bytes, display_name: str = "PLAYER") -> str:
    command = root.tag
    user_id = session["user_id"]
    profile = store.profile(user_id)
    settings = set_handling(profile["legacy_settings"], profile["settings"])
    if command == "LoginOpenWebRQ":
        # The movie's identity is local to this launch, never a Commons account id.
        body = (f'<SessionKey>{escape(root.findtext("SessionId", ""))}</SessionKey>'
                f'<UserOpenWebId>1</UserOpenWebId><UserName>{escape(display_name)}</UserName>'
                f'<AvatarURL>0.gif</AvatarURL><Settings>{settings}</Settings>')
    elif command == "GameInitSprintRQ":
        items = "".join(f"<UserAccessory><Accessory><Id>{i}</Id><IsNew>false</IsNew>"
                        "<Name>Handling</Name><PriceInPoints>0</PriceInPoints><Type>9</Type>"
                        "</Accessory></UserAccessory>" for i in range(9000, 9012))
        body = f"<HalfStars>4</HalfStars><Rank>1</Rank><HasPlayedToday>false</HasPlayedToday><BestScoreToday>false</BestScoreToday><UserAccessories>{items}</UserAccessories>"
    elif command == "GameStartRQ":
        run_id = store.start_run(session)
        body = f"<GameToken>{run_id}</GameToken><Points>0</Points><Rubies>0</Rubies>"
    elif command == "UpdateUserOpenWebSettingsRQ":
        saved = parse_xml(root.findtext("Settings", ""))
        if saved.tag != "UserSettings":
            raise ValueError("Invalid settings")
        values = dict(profile["settings"])
        das_id = int(saved.findtext("CurDas", "9001"))
        arr_id = int(saved.findtext("CurArr", "9007"))
        if not 9000 <= das_id <= 9004 or not 9006 <= arr_id <= 9010:
            raise ValueError("Unsupported handling level")
        values["das_ms"] = DAS[das_id - 9000]
        values["arr_ms"] = ARR[arr_id - 9006]
        store.save_profile(user_id, values, ET.tostring(saved, encoding="unicode"))
        body = ""
    elif command == "CreateSprintGameRecordRQ":
        metrics, record = metrics_and_record(root)
        store.save_run(session, metrics, record)
        body = ""
    elif command == "GameCompletedRQ":
        store.save_run(session, {child.tag: child.text for child in root if child.tag in {"GameLength", "GameLevel"}})
        body = ""
    else:
        raise ValueError("Unsupported game operation")
    return response(command, body)

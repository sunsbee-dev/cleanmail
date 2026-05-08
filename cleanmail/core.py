import re
import json
import base64
import extract_msg
from bs4 import BeautifulSoup

ORDINALS = ["first", "second", "third", "fourth", "fifth",
            "sixth", "seventh", "eighth", "ninth", "tenth"]


def extract_email_address(text):
    """Extract email address from string เช่น 'John Doe <john@example.com>' → 'john@example.com'"""
    text = text.strip().replace('\u0000', '')
    match = re.match(r'^(.*?)\s*<([^>]+)>$', text)
    if match:
        return match.group(2).strip()
    elif "@" in text:
        return text
    return text

def parse_recipients(text):
    """
        Parse a recipient string separated by ';' → list of email addresses
        Arguments:
            text: string e.g. "John Doe <john@example.com>; jane@example.com"
        Returns:
            list of email addresses e.g. ["john@example.com", "jane@example.com"]
        """
    if not text:
        return []
    parts = re.split(r';\s*', text)
    return [extract_email_address(p.strip()) for p in parts if p.strip()]


def parse_header_div(div):
    """Parse header from divRplyFwdMsg div → dict {from, sent, to, cc, subject}"""
    header = {"from": None, "sent": None, "to": [], "cc": [], "subject": None}
    if not div:
        return header

    text = div.get_text(separator="\n")
    fields = ["From", "Sent", "To", "Cc", "Subject", "When", "Where",
            "จาก", "ส่ง", "ถึง", "สำเนาถึง", "ชื่อเรื่อง", "Date"]
    field_pattern = "(?:" + "|".join(fields) + ")"

    patterns = {
        "from":    rf"(?:From|จาก):\s*(.*?)(?=\n{field_pattern}:|$)",
        "sent": rf"(?:Sent|ส่ง|Date):\s*(.*?)(?=\n{field_pattern}:|$)",
        "to":      rf"(?:To|ถึง):\s*(.*?)(?=\n{field_pattern}:|$)",
        "cc":      rf"(?:Cc|สำเนาถึง):\s*(.*?)(?=\n{field_pattern}:|$)",
        "subject": rf"(?:Subject|ชื่อเรื่อง):\s*(.*?)(?=\n{field_pattern}:|$)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            value = " ".join(match.group(1).split()).replace('\u0000', '')
            if key == "from":
                header["from"] = extract_email_address(value)
            elif key in ("to", "cc"):
                header[key] = parse_recipients(value)
            else:
                header[key] = value

    return header


def parse_header_from_injectable(msg):
    """Parse header from msg.htmlInjectableHeader → dict {from, sent, to, cc, subject},
    this case for newest email, header will be store in htmlInjectableHeader """
    header_html = msg.htmlInjectableHeader
    if not header_html:
        return {"from": None, "sent": None, "to": [], "cc": [], "subject": None}

    soup = BeautifulSoup(header_html, "html.parser")
    text = soup.get_text(separator="\n")

    class FakeDiv:
        def get_text(self, **kwargs):
            return text

    return parse_header_div(FakeDiv())


def parse_header_from_blockquote(bq):
    """
    Parse header from a replied email where the header is embedded in collapsed HTML
    in the format 'On ... wrote:' → dict {from, sent}
    """
    header = {"from": None, "sent": None, "to": [], "cc": [], "subject": None}
    if not bq:
        return header

    text = bq.get_text()
    match = re.search(
        r'On\s+(\d+\s+\w+\s+\d+),?\s+at\s+([\d:]+\s*[apm]+),\s+(.+?)\s+<([^>]+)>\s+wrote:',
        text, re.DOTALL | re.IGNORECASE
    )
    if match:
        header["sent"] = f"{match.group(1)} at {match.group(2)}"
        header["from"] = match.group(4).strip()
    return header


def html_to_clean_text(html_fragment):
    """Convert HTML fragment → clean text which table will turn to markdown"""
    if not html_fragment:
        return ""

    soup = BeautifulSoup(str(html_fragment), "html.parser")

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        markdown_rows = []
        for i, row in enumerate(rows):
            cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
            if not any(cells):
                continue
            markdown_rows.append("| " + " | ".join(cells) + " |")
            if i == 0:
                markdown_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        table.replace_with(soup.new_string("\n".join(markdown_rows)))

    raw = soup.get_text(separator="\n")
    lines = [line.strip() for line in raw.splitlines()]

    clean = []
    for line in lines:
        if line:
            clean.append(line)
        elif clean and clean[-1] != "":
            clean.append("")

    text = "\n".join(clean).replace('\xa0', ' ').replace('\ufeff', '').strip()

    lines = text.split("\n")
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if i < len(lines) - 1:
            next_line = lines[i + 1]
            if line.startswith("|") or next_line.startswith("|"):
                result.append("\n")
            else:
                result.append(" ")

    return "".join(result).strip()


def get_body_without_disclaimer(chunk_html):
    """delete disclaimer, PTT footer, Outlook signature and quoted blockquote from mail chunk """
    soup = BeautifulSoup(chunk_html, "html.parser")

    for hr in soup.find_all("hr"):
        next_div = hr.find_next("div", id=lambda x: x and x.endswith("divRplyFwdMsg"))
        if not next_div and hr.parent.name in ["[document]", "body"]:
            for sib in list(hr.next_siblings):
                sib.decompose()
            hr.decompose()
            break

    # ลบ Outlook signature div
    for sig in soup.find_all("div", id=lambda x: x and x.endswith("Signature")):
        sig.decompose()

    # ลบ blockquote[type="cite"] (Apple Mail / mobile quoted reply)
    for bq in soup.find_all("blockquote", attrs={"type": "cite"}):
        bq.decompose()

    return soup


def parse_chunk(chunk_html, header, thread_index):
    """Parse one HTML chunk  → list of thread dicts"""
    soup = get_body_without_disclaimer(chunk_html)

    header_div = soup.find("div", id=lambda x: x and x.endswith("divRplyFwdMsg"))
    if header_div:
        header_div.decompose()

    bqs = [tag for tag in soup.find_all("blockquote")
           if not tag.find_parent("blockquote")]

    threads = []

    if not bqs:
        threads.append({
            "thread_index": thread_index,
            "_from_blockquote": False,
            **header,
            "body": html_to_clean_text(str(soup))
        })
        return threads

    body_parts = []
    for elem in soup.children:
        if elem == bqs[0]:
            break
        body_parts.append(str(elem))

    threads.append({
        "thread_index": thread_index,
        "_from_blockquote": False,
        **header,
        "body": html_to_clean_text("".join(body_parts))
    })

    i = 0
    sub_index = thread_index + 1
    while i < len(bqs):
        bq_header = parse_header_from_blockquote(bqs[i])
        body_bq = html_to_clean_text(str(bqs[i + 1])) if i + 1 < len(bqs) else ""

        threads.append({
            "thread_index": sub_index,
            "_from_blockquote": True,
            **bq_header,
            "body": body_bq
        })

        i += 2
        sub_index += 1

    return threads


def assign_thread_types(threads):
    """define type for thread such as first_email, first_reply_to_first_email"""
    threads = list(reversed(threads))

    result = []
    ordinal_count = 0
    reply_count = 0
    forward_count = 0
    last_email_type = None

    for t in threads:
        subject = (t.get("subject") or "").strip()
        if subject.lower().startswith("re:") or subject.startswith("ตอบกลับ:"):
            reply_count += 1
            ordinal = ORDINALS[reply_count - 1] if reply_count <= len(ORDINALS) else f"reply_{reply_count}"
            t["type"] = f"{ordinal}_reply_to_{last_email_type}" if last_email_type else f"{ordinal}_reply"

        elif subject.startswith("FW:") or subject.startswith("Fw:") or subject.startswith("ส่งต่อ:"):
            forward_count += 1
            ordinal = ORDINALS[forward_count - 1] if forward_count <= len(ORDINALS) else f"forward_{forward_count}"
            t["type"] = f"{ordinal}_forward_of_{last_email_type}" if last_email_type else f"{ordinal}_forward"

        else:
            reply_count = 0
            forward_count = 0
            t["type"] = f"{ORDINALS[ordinal_count]}_email" if ordinal_count < len(ORDINALS) else f"email_{ordinal_count+1}"
            last_email_type = t["type"]
            ordinal_count += 1

        t.pop("_from_blockquote", None)
        t.pop("thread_index", None)
        result.append(t)

    return result


def reorder_thread(t, attachments=None):
    """sort field for thread correctly"""
    return {
        "type": t.get("type"),
        "from": t.get("from"),
        "sent": t.get("sent"),
        "subject": t.get("subject") or [],
        "body": t.get("body"),
        "attachments": attachments or [],
        "to": t.get("to"),
        "cc": t.get("cc"),
    }


def clear(msg):
    """
    Parse Outlook .msg file → JSON string พร้อมส่ง LLM

    Args:
        msg: extract_msg.Message object

    Returns:
        JSON string ที่มี structure:
        {
            "threads": [
                {
                    "type": "first_email" | "second_email" | ... |
                            "first_reply_to_first_email" | ...,
                    "from": "email@example.com",
                    "sent": "...",
                    "subject": "..." | [],
                    "body": "...",
                    "attachments": [{"filename": ..., "mimetype": ..., "data": ...}],
                    "to": ["email1@x.com"],
                    "cc": ["email1@x.com"]
                },
                ...
            ]
        }
    """

    attachments = []
    for att in msg.attachments:
        if att.data and att.mimetype and 'image' in att.mimetype and not (att.cid or "").strip().replace('\x00', ''):
            
            attachments.append({
                "filename": (att.longFilename or att.shortFilename or "").replace('\u0000', ''),
                "mimetype": (att.mimetype or "").replace('\u0000', ''),
                "data": base64.standard_b64encode(att.data).decode('utf-8')
            })

    html = msg.htmlBody
    if not html:
        header = parse_header_from_injectable(msg)
        threads = assign_thread_types([{
            "thread_index": 0,
            "_from_blockquote": False,
            **header,
            "body": html_to_clean_text(msg.htmlBodyPrepared)
        }])
        return {"threads": [reorder_thread(t, attachments if i == 0 else [])
                for i, t in enumerate(threads)]}

    if isinstance(html, bytes):
        try:
            html = html.decode('utf-8')
        except UnicodeDecodeError:
            html = html.decode('tis-620', errors='ignore')

    soup = BeautifulSoup(html, "html.parser")

    thread_separators = []
    for hr in soup.find_all("hr"):
        next_div = hr.find_next("div", id=lambda x: x and x.endswith("divRplyFwdMsg"))
        if next_div:
            thread_separators.append(hr)

    mobile_div_headers = []
    for div in soup.find_all("div"):
        style = div.get("style", "")
        if "border-style:solid none none" in style or "border-width:1pt medium medium" in style:
            text = div.get_text()
            if "From:" in text or "จาก:" in text:
                mobile_div_headers.append(parse_header_div(div))
                thread_separators.append(div)

    all_elements = list(soup.find_all(True))
    thread_separators.sort(key=lambda x: all_elements.index(x))

    if not thread_separators:
        header = parse_header_from_injectable(msg)
        threads = assign_thread_types([{
            "thread_index": 0,
            "_from_blockquote": False,
            **header,
            "body": html_to_clean_text(html)
        }])
        return {"threads": [reorder_thread(t, attachments if i == 0 else [])
                for i, t in enumerate(threads)]}

    marker = "___THREAD_SPLIT___"
    html_str = str(soup.body)
    for elem in thread_separators:
        html_str = html_str.replace(str(elem), marker, 1)
    chunks = html_str.split(marker)

    all_threads = []
    thread_index = 0

    header0 = parse_header_from_injectable(msg)
    threads0 = parse_chunk(chunks[0], header0, thread_index)
    all_threads.extend(threads0)
    thread_index += len(threads0)

    mobile_index = 0
    for chunk in chunks[1:]:
        chunk_soup = BeautifulSoup(chunk, "html.parser")

        header_div = chunk_soup.find("div", id=lambda x: x and x.endswith("divRplyFwdMsg"))

        if header_div:
            h = parse_header_div(header_div)
        else:
            h = mobile_div_headers[mobile_index] if mobile_index < len(mobile_div_headers) else {}
            mobile_index += 1

        threads = parse_chunk(chunk, h, thread_index)
        all_threads.extend(threads)
        thread_index += len(threads)

    threads = assign_thread_types(all_threads)
    reordered = []
    for i, t in enumerate(threads):
        reordered.append(reorder_thread(t, attachments if i == 0 else []))
    return json.dumps({"threads": reordered}, ensure_ascii=False, indent=2)
# cleanmail

![PyPI version](https://img.shields.io/pypi/v/cleanmail)
![Python](https://img.shields.io/pypi/pyversions/cleanmail)
![License](https://img.shields.io/pypi/l/cleanmail)

A Python library for parsing Outlook `.msg` email threads into structured JSON, ready for LLM processing.

## Features

- Parses nested email threads from `.msg` files
- Handles multiple email clients (Outlook, Apple Mail, mobile)
- Extracts From, To, Cc, Subject, Body, Attachments per thread
- Converts HTML tables to Markdown
- Removes disclaimers, signatures, and quoted content automatically
- Returns structured JSON ready to send to LLM

## Installation

```bash
pip install cleanmail
```

## Requirements

- Python 3.8+
- `extract-msg`
- `beautifulsoup4`

## Usage

```python
import extract_msg
import cleanmail

msg = extract_msg.Message("path/to/your/file.msg")
result = cleanmail.clear(msg)
print(result)
```

## Output Format

```json
{
  "threads": [
    {
      "type": "first_email",
      "from": "sender@example.com",
      "sent": "Wednesday, April 22, 2026 11:25",
      "subject": "Meeting Invitation",
      "body": "Dear all, ...",
      "attachments": [
        {
          "filename": "document.png",
          "mimetype": "image/png",
          "data": "<base64 encoded string>"
        }
      ],
      "to": ["recipient@example.com"],
      "cc": ["cc@example.com"]
    },
    {
      "type": "first_reply_to_first_email",
      "from": "recipient@example.com",
      "sent": "Wednesday, April 22, 2026 14:30",
      "subject": "Re: Meeting Invitation",
      "body": "Confirmed.",
      "attachments": [],
      "to": ["sender@example.com"],
      "cc": []
    }
  ]
}
```

## Thread Types

| Type | Description |
|------|-------------|
| `first_email` | First email in the chain |
| `second_email` | Second standalone email |
| `first_reply_to_first_email` | First reply to the first email |
| `second_reply_to_first_email` | Second reply to the first email |
| `first_forward_of_first_email` | First forward of the first email |

## License

MIT © [sunsbee-dev](https://github.com/sunsbee-dev)
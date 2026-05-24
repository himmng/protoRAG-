"""Extract @"filename" / @filename tokens from a chat message."""

import re


def parse_at_mentions(message: str) -> tuple[list[str], str]:
    pattern = r'@"([^"]+)"|@(\S+)'
    mentions = [m.group(1) or m.group(2) for m in re.finditer(pattern, message)]
    cleaned = re.sub(pattern, "", message).strip()
    return mentions, cleaned

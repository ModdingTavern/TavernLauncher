"""Portable moderator credentials. This code is private, not encrypted."""
import base64
import json

PREFIX = 'pfac1.'


def make_code(host, token):
    host = host.strip()
    if not host or any(c.isspace() or c in '/?#@\\' for c in host):
        raise ValueError('Use a server hostname or IP address.')
    if not isinstance(token, str) or not token.startswith('pfa1.'):
        raise ValueError('Only personal tokens can be shared as moderator codes.')
    raw = json.dumps({'host': host, 'token': token}, separators=(',', ':')).encode()
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip('=')


def read_code(code):
    try:
        code = code.strip()
        if not code.startswith(PREFIX) or len(code) > 4096:
            raise ValueError()
        data = code[len(PREFIX):]
        value = json.loads(base64.b64decode(data + '=' * (-len(data) % 4), altchars=b'-_', validate=True))
        host, token = value['host'], value['token']
        make_code(host, token)
        return host, token
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError('Invalid moderator code. Ask the owner to copy a new code.') from None

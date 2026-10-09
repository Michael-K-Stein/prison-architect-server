"""The capture file format: its tables, schema version and direction codes.

Tables (all integers unless noted):

``meta(key, value)``
    ``format`` (schema version), ``created_ns``.
``sessions(id, started_ns, client TEXT, upstream TEXT)``
    One row per client connection through a proxy hop.
``packets(id, ts_ns, session, dir, command, format, code, encrypted,
protocol, return_code, size, payload BLOB)``
    One row per packet, in arrival order (``id``). ``dir`` is 0 for
    client -> server and 1 for server -> client. ``command`` is the
    ``CommandCode`` and ``code`` the operation or event code (NULL for
    packets without one, such as keep-alives). ``payload`` is the *plaintext*
    body: encrypted operations are already decrypted. For operations,
    responses and events it is the serialized payload (starting at the
    operation code byte); for anything else, the whole packet.
    Addresses are recorded as the real server sent them, before the proxy
    rewrites them.
"""

FORMAT_VERSION = 1
TO_SERVER, TO_CLIENT = 0, 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_ns INTEGER NOT NULL,
    client TEXT,
    upstream TEXT
);
CREATE TABLE IF NOT EXISTS packets (
    id INTEGER PRIMARY KEY,
    ts_ns INTEGER NOT NULL,
    session INTEGER NOT NULL,
    dir INTEGER NOT NULL,
    command INTEGER,
    format INTEGER NOT NULL,
    code INTEGER,
    encrypted INTEGER NOT NULL,
    protocol INTEGER NOT NULL,
    return_code INTEGER,
    size INTEGER NOT NULL,
    payload BLOB
);
CREATE INDEX IF NOT EXISTS packets_session ON packets (session, id);
CREATE INDEX IF NOT EXISTS packets_code ON packets (command, code, id);
"""

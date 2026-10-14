"""Napier: a device knowledge store.

Sources (manuals, firmware changelogs, community docs) are listed in sources.yaml, fetched into
~/.napier, and turned into a text layer (one unit per PDF page or per document section) that
`grep` and `read` use directly. `ingest` also builds a hybrid vector + BM25 index for `search`.
Checked facts live in facts/<device>.yaml with where each one came from.

Citations use the page number printed in the manual, so you can turn straight to it.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("napier")      # pyproject.toml is the one place the version is written
except PackageNotFoundError:             # running from a checkout that isn't installed
    __version__ = "0.0.0+unknown"

# napier: third-party notices

napier is Apache-2.0. It uses, but does not include, the following. Each is installed or downloaded
separately and keeps its own license.

## Manuals, changelogs and other documents

`sources.yaml` lists where each document lives: a URL, a checksum, a version, a page offset. napier
downloads each one from its publisher onto the user's machine, for that user's own reference. The
repository doesn't contain the documents. Facts in `facts/` and specs in `specs/` paraphrase what a
page says and quote short anchor phrases from it, with the source and page, so the claim can be
checked against the original (at most 25 words each). The documents and the quoted anchors remain
their publishers' work under their terms; [docs/data-policy.md](docs/data-policy.md) says how a
publisher can ask for a change.

Forum threads are fetched once through Discourse's public `/raw` pages, where the forum's robots.txt
allows it, and are cited as community reports. Firmware source code sources point at public
repositories, pinned to one commit, under those repositories' licenses.

## Search models (the `[index]` extra)

Downloaded from Hugging Face on first use into the Hugging Face cache:

| Model | Used for | License (model card) |
|---|---|---|
| `Snowflake/snowflake-arctic-embed-l-v2.0` (pinned commit) | embeddings | Apache-2.0 |
| `BAAI/bge-reranker-v2-m3` (pinned commit) | reranking | Apache-2.0 |
| `docling-project/docling-layout-heron`, `docling-project/docling-models` | PDF layout and table parsing (through Docling) | Apache-2.0; `docling-models` also lists CDLA-Permissive-2.0 |

## Python packages

| Package | License |
|---|---|
| click | BSD-3-Clause |
| rich | MIT |
| PyYAML | MIT |
| pypdfium2 (and PDFium) | BSD-3-Clause, Apache-2.0 |
| Docling (`[index]`) | MIT |
| LanceDB (`[index]`) | Apache-2.0 |
| sentence-transformers (`[index]`, brings PyTorch and Transformers) | Apache-2.0 |
| mcp (`[mcp]`) | MIT |

## Optional tools

- [Ollama](https://ollama.com) (MIT), if you let `napier refresh` reword eval questions with a local
  model; the model you choose keeps its own license.
- The GitHub CLI `gh` (MIT), if `napier refresh` opens pull requests.

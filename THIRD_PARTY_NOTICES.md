# Third-party notices

RescueBridge's own code is licensed under Apache-2.0 (see `LICENSE`). It uses the third-party packages
below, unmodified, under their own licenses. Versions are pinned in `uv.lock` and `web/package-lock.json`.
License identifiers were read from each installed package's metadata on 2026-10-20 (not typed from memory);
check the upstream projects for full license texts.

## Python runtime and tooling (installed into `.venv` by `uv sync --frozen`)

| Package | Version | License (package metadata) |
|---|---|---|
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD |
| comtypes | 1.4.17 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.15.1 | BSD-3-Clause |
| httpx2 | 2.15.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp (Model Context Protocol Python SDK) | 2.3.0 | MIT |
| mcp-types | 2.3.0 | MIT |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| psutil | 7.2.2 | BSD-3-Clause |
| pycaw | 20260927 | MIT |
| pycparser | 3.11 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| PyJWT | 2.15.1 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | Python Software Foundation License |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| segno | 1.6.6 | BSD |
| sse-starlette | 3.5.0 | BSD-3-Clause |
| starlette | 1.9.0 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

Development only (not needed to run): mypy 2.4.0 (MIT), mypy_extensions 1.1.0 (MIT), pytest 9.1.1 (MIT),
pluggy 1.7.0 (MIT), iniconfig 2.3.1 (MIT), Pygments 2.21.0 (BSD-2-Clause), ruff 0.17.1 (MIT),
packaging 26.3 (Apache-2.0 OR BSD-2-Clause), pathspec 1.1.1 (MPL-2.0), librt 0.16.0 (MIT),
ast_serialize 0.13.1 (MIT).

## Web build tooling (`web/`, development only)

| Package | Version | License |
|---|---|---|
| vite | 8.3.4 | MIT |
| typescript | 6.0.3 | Apache-2.0 |

The built browser bundle (`web/dist`) contains only RescueBridge's own TypeScript compiled by these tools;
no third-party runtime library is shipped to the browser.

## Not bundled

- Ollama and any local language model are separate, optional software installed by the user. RescueBridge
  never downloads models. Model licenses (e.g. Qwen2.5) are the user's responsibility to review.
- Browser speech recognition/synthesis are provided by the user's browser.

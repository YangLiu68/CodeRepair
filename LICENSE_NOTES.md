# License notes

## Project license

**Not chosen yet.** No `LICENSE` file has been added because the license is the repository owner's
decision. Until one is added, default copyright applies. MIT or Apache-2.0 would be compatible with
every dependency below. `pyproject.toml` says "TBD" until then.

## Benchmark fixtures

All ten tasks under `benchmarks/tasks/` (code, tests, hidden tests, issues and solutions) are
original work written for this project on 2026-10-14. They are not copied or adapted from public
repositories or bug datasets, and they will be released under the project license. The prompt-injection
text in t10 is synthetic and points only at the reserved `attacker.example` domain.

Any future public tasks (Milestone 6) must come from repositories with a license that permits
redistribution and modification. Each task must record its upstream repository, commit, license and
retrieval date in `task.toml`.

## Runtime dependencies

| Package | License |
|---|---|
| fastapi | MIT |
| starlette | BSD-3-Clause |
| pydantic, pydantic-core | MIT |
| uvicorn | BSD-3-Clause |
| httpx, httpcore | BSD-3-Clause |
| anyio | MIT |
| h11 | MIT |
| idna | BSD-3-Clause |
| certifi | MPL-2.0 (used unmodified) |
| typing-extensions | PSF-2.0 |
| annotated-types | MIT |
| click | BSD-3-Clause |
| sniffio | MIT OR Apache-2.0 |
| anthropic (optional extra) | MIT |
| httpx2, jiter (via anthropic) | BSD-3-Clause, MIT |

Development only: pytest (MIT), ruff (MIT), hatchling (MIT, build backend). Versions are pinned in
`uv.lock`. Licenses were read from installed package metadata on 2026-10-14.

## Models and services

- **Claude (Anthropic API):** used through the API under Anthropic's terms. Repository content in a
  prompt is sent to Anthropic; secrets are redacted on a best-effort basis first.
- **qwen2.5:7b (Ollama):** run locally for the smoke test and not redistributed. Its model card lists
  Apache-2.0; check the card before redistributing weights or outputs commercially.
- No model weights, datasets or third-party code are included in this repository.

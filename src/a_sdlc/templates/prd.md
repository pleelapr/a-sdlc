# /sdlc:prd - PRD Management

Product Requirements Document ingestion and management pipeline.

## Available Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:prd-generate "<desc>"` | Interactive PRD creation |
| `/sdlc:prd-list` | List all PRDs |
| `/sdlc:prd-update "<id>"` | Update existing PRD |
| `/sdlc:prd-split "<id>"` | Generate tasks from PRD |

## Usage

This is a command group. Use one of the subcommands above.

Example:
```
/sdlc:prd-generate "Add OAuth authentication"
/sdlc:prd-list
/sdlc:prd-split "feature-auth"
```

## Quick Start

1. **Create PRD**: `/sdlc:prd-generate "your feature description"`
2. **View PRDs**: `/sdlc:prd-list`
3. **Generate tasks**: `/sdlc:prd-split "<prd-id>"`
4. **Update PRD**: `/sdlc:prd-update "<prd-id>"`

## Storage

PRDs are stored in `.sdlc/prds/` directory:
- `{slug}.md` - PRD content
- `.metadata.json` - Version and history tracking

## Notes

- PRDs are stored in `.sdlc/prds/` directory (auto-created when needed)
- Metadata is tracked in `.sdlc/prds/.metadata.json`
- Cross-referencing with artifacts requires artifacts to exist (run `/sdlc:scan` first)
- PRD generation uses interactive questions to guide creation

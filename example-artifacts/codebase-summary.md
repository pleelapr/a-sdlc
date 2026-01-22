# Codebase Summary

## Overall Purpose & Domain
The primary goal of this application is to generate Dungeons and Dragons (D&D) 5th Edition adventures. It operates as an AI agent system, specifically designed to automate the creative process of outlining, detailing, and writing various components of an adventure, such as chapters, encounters, locations, items, NPCs, and monsters. The intended users are D&D Dungeon Masters or content creators who require assistance in generating detailed and structured adventure content. The core real-world problem the application addresses is the time-consuming and complex nature of creating comprehensive D&D adventure modules.

## Key Concepts & Domain Terminology
*   **AdventureOutline:** The high-level structure of an entire D&D adventure, including its name, number of chapters, story synopsis, and a list of chapters.
*   **Chapter:** A major section of an adventure, defined by a number, name, synopsis, and a list of encounters.
*   **Encounter:** A specific event or challenge within a chapter, characterized by a number, name, objectives, setting, detail, location, active NPCs, monsters, traps, treasures, conflict, and whether it is a boss fight.
*   **Location:** A specific place within the adventure, including its name, narrative, chapter association, additional narrative, role, and a list of areas.
*   **Area:** A distinct part of a location, described by its name, narrative, and key investigation or skill checks.
*   **AreaKey:** A specific interactive element or challenge within an area, detailing its name, skill check, difficulty class (DC), description, and success/failure outcomes.
*   **Item:** A tangible object within the adventure, defined by its name, type, attunement requirement, rarity, physical appearance, description, narrative, founded location, backstory, features, range, bonus, damage, and value.
*   **ItemFeature:** A specific characteristic or ability of an item, with a name and description.
*   **CharacterBase:** A foundational schema for characters, including description, physical appearance, alignment, size, stat block, saving throws, armor class, speed, hit points (HP), challenge rating (CR), proficiency bonus, damage immunities/resistances, condition immunities, senses, languages, skills, actions, legendary actions, feats, spells, backstory, and additional details.
*   **Monster:** A type of character representing an adversary, inheriting from `CharacterBase`, with specific monster name, type, and optional boss mechanics.
*   **NPC (Non-Player Character):** A type of character representing an inhabitant of the world, inheriting from `CharacterBase`, with specific character name, NPC type, race, and roleplaying guidance.
*   **StatBlock:** A collection of numerical attributes for a character, including strength, dexterity, constitution, intelligence, wisdom, and charisma (each with modifier).
*   **Action:** A specific ability or attack a character can perform, with a name and description.
*   **Spell:** A magical ability a character can cast, with a name and description.
*   **Feats:** Special abilities or talents a character possesses, with a name and description.
*   **BossMechanic:** A specific phase or ability of a boss monster, including its stage order, trigger condition, and description.
*   **SubSection:** A granular content block within a chapter, with a number, name, detail, type, and level (for markdown heading hierarchy).
*   **TableOfContent:** A comprehensive index of the adventure's content, listing chapters, characters, and items.

## Data Persistence & State Management
The application uses a combination of file-based storage, cloud storage, and database systems for data persistence and state management.

**Data Persistence:**
*   **PostgreSQL (image: postgres 16):** Used as the primary database, as indicated by the `postgres:16` image in `docker-compose.yml` and the `DATABASE_URI` environment variable. It serves as the backend for the `langgraph-api`.
*   **Redis (image: redis 7):** Used as a caching or message queue system, as indicated by the `redis:7` image in `docker-compose.yml` and the `REDIS_URI` environment variable. It supports the `langgraph-api`.
*   **Azure Blob Storage (client: azure-storage-blob 12.25.1):** Used for publishing and storing generated content, specifically Markdown, PDF, and DOCX files. The `write_md_to_azure_blob` function and `AZURE_STORAGE_CONNECTION_STRING` environment variable confirm this.
*   **Local File System:** Generated content (Markdown, JSON, PDF, DOCX) can be written to the local file system, as evidenced by functions like `write_text_to_md`, `write_json`, `write_md_to_pdf`, and `write_md_to_word` in `src/agent/utils/file_formats.py`.

**State Management:**
*   **LangGraph:** The core framework for orchestrating the agent workflow. LangGraph manages the overall state of the multi-agent system, allowing agents to pass information and decisions between each other.
*   **TypedDict States:** Python `TypedDict` classes (`InputState`, `OutlineState`, `OutputState`, `InterviewState`, `SectionImproverState`, `SectionTextState`) are used to define the structure of data passed between nodes in the LangGraph workflow. These states hold intermediate results, user inputs, agent outputs, and references throughout the adventure generation process.
*   **In-memory State:** During the execution of a graph, the state is managed in memory within the LangGraph framework, with persistence to PostgreSQL and Redis handled by the `langgraph-api` layer.

## External Dependencies & APIs
The application integrates with several external services and APIs to enhance its content generation capabilities.

*   **OpenAI (client: langchain-openai 0.3.16):** Used for large language model (LLM) interactions, including generating outlines, detailed sections, and improving prompts. The `ChatOpenAI` and `AsyncOpenAI` clients are used for this purpose.
*   **Tavily Search (client: tavily-python 0.7.2, langchain-tavily 0.1.0):** Utilized as a search tool within the agent workflow, specifically for retrieving information to inform content generation, as explicitly defined in `tools.py`.
*   **Wikipedia (client: wikipedia 1.4.0):** Used by the `EditorSelectorAgent` to survey subjects and gather related information for idea expansion.
*   **Azure Blob Storage (client: azure-storage-blob 12.25.1):** Used for publishing the final generated adventure documents to cloud storage.
*   **LangSmith (version unknown):** Used for tracing and monitoring the LangGraph agent executions, indicated by `LANGSMITH_API_KEY` in `docker-compose.yml` and `@traceable` decorators in the code.
*   **DuckDuckGo Search (client: duckduckgo-search 8.0.1):** Listed as a dependency in `pyproject.toml` and `Dockerfile`, indicating its availability as a potential search tool, though Tavily Search is explicitly configured in `tools.py`.

## Configuration, Deployment & Environment
**Configuration Mechanisms:**
*   **Environment Variables:** Critical configurations such as API keys (`OPENAI_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY`, `AZURE_STORAGE_CONNECTION_STRING`) and database/Redis URIs (`DATABASE_URI`, `REDIS_URI`) are managed through environment variables, as seen in `docker-compose.yml` and `langgraph.json`.
*   **`.env` file:** The `docker-compose.yml` references an `.env` file for environment variable loading, and `langgraph.json` also specifies `env: ".env"`.
*   **Python Code:** Model names (`gpt-5-nano`, `gpt-5-mini`, `gpt-4.1-nano`, `gpt-4.1-mini`) are configured directly within the Python code, for example, in `src/agent/utils/nodes.py` and `src/agent/graph.py`.

**CI/CD & Automation:**
No CI/CD pipeline configuration files (e.g., `.github/workflows/`, `.gitlab-ci.yml`) are present in the provided directory structure, indicating that a CI/CD pipeline is not currently implemented.

**Build & Deployment Strategy:**
*   **Docker (version unknown):** The application is containerized using Docker. A `Dockerfile` builds a custom image based on `langchain/langgraph-api:3.11`, installing additional Python dependencies and adding the local codebase.
*   **Docker Compose (version unknown):** `docker-compose.yml` orchestrates the deployment of the application's services, including PostgreSQL, Redis, and the `langgraph-api` service. This indicates a multi-service, containerized deployment approach.
*   **LangGraph API:** The application is deployed as a LangGraph API service, exposing the `realmforge-agent` workflow. The `ENV LANGSERVE_GRAPHS` variable in the `Dockerfile` points to the `workflow` object in `src/agent/graph.py`.

## Technology Stack
*   **Languages and Runtimes:**
    *   Python (versions >=3.11.0 and <3.13)
*   **Frameworks and Libraries:**
    *   LangGraph (version 0.4.3)
    *   LangChain (version 0.3.25)
    *   LangChain Community (version 0.3.24)
    *   LangChain OpenAI (version 0.3.16)
    *   LangChain Tavily (version 0.1.0)
    *   Pydantic (version unknown - inferred from BaseModel usage)
    *   Aiofiles (version 24.1.0)
    *   Mistune (version 3.1.3)
    *   Colorama (version 0.4.6)
    *   Wasabi (version 1.1.3)
    *   Setuptools (version >=73.0.0)
    *   Wheel (version unknown)
    *   Python-dotenv (version 1.0.1)
    *   Pytest (version >=8.3.5) - for testing
    *   Anyio (version >=4.7.0) - for testing
    *   Mypy (version >=1.13.0) - for development
    *   Ruff (version >=0.8.2) - for development
    *   Langgraph-cli (version >=0.2.8) - for development
*   **Databases and Data Stores:**
    *   PostgreSQL (image: postgres 16)
    *   Redis (image: redis 7)
*   **External Services and APIs:**
    *   OpenAI (client: langchain-openai 0.3.16)
    *   Tavily Search (client: tavily-python 0.7.2)
    *   Wikipedia (client: wikipedia 1.4.0)
    *   DuckDuckGo Search (client: duckduckgo-search 8.0.1)
    *   Azure Blob Storage (client: azure-storage-blob 12.25.1)
    *   Azure Core (client: azure-core 1.34.0)
    *   Azure Identity (client: azure-identity 1.19.0)
    *   LangSmith (version unknown)
*   **Deployment Tools:**
    *   Docker (version unknown)
    *   Docker Compose (version unknown)
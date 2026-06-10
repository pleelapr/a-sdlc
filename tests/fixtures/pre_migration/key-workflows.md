# Key Workflows / Interactions

The following key workflows were identified based on code analysis using specified heuristics, focusing on the LangGraph agent's adventure generation process.

**Phase 1: Workflow List**

1. [Adventure Generation Orchestration](#1-adventure-generation-orchestration)
2. [Prompt Improvement](#2-prompt-improvement)
3. [Editor Selection and Subject Survey](#3-editor-selection-and-subject-survey)
4. [Interview Question Generation](#4-interview-question-generation)
5. [Interview Answer Generation with Citations](#5-interview-answer-generation-with-citations)
6. [Interview Summary Generation](#6-interview-summary-generation)
7. [Initial Adventure Outline Drafting](#7-initial-adventure-outline-drafting)
8. [Table of Content Generation](#8-table-of-content-generation)
9. [Section Outline Commenting](#9-section-outline-commenting)
10. [Section Outline Improvement](#10-section-outline-improvement)
11. [Subsection Text Writing](#11-subsection-text-writing)
12. [Subsection Text Commenting](#12-subsection-text-commenting)
13. [Statblock Content Writing](#13-statblock-content-writing)
14. [Item Content Writing](#14-item-content-writing)
15. [Full Document Content Assembly](#15-full-document-content-assembly)
16. [Markdown File Writing](#16-markdown-file-writing)
17. [JSON File Writing](#17-json-file-writing)
18. [Markdown to PDF Conversion](#18-markdown-to-pdf-conversion)
19. [Markdown to Word Conversion](#19-markdown-to-word-conversion)
20. [Markdown to Azure Blob Upload](#20-markdown-to-azure-blob-upload)

The codebase contains 20 distinct workflows due to its focused scope on generating Dungeons and Dragons adventures through a multi-agent LangGraph system.

## Workflow Details

### 1. Adventure Generation Orchestration
This workflow orchestrates the entire adventure generation process, chaining various agents to produce a complete adventure document.

**Main Components:**
- `src/agent/graph.py`
- `src/agent/utils/state.py`
- `src/agent/utils/prompt_improver.py`
- `src/agent/utils/editor_selector.py`
- `src/agent/utils/interview_graph.py`
- `src/agent/utils/outliner.py`
- `src/agent/utils/table_of_content_agent.py`
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/publisher_agent.py`

**Relevance:**
- Primary Entry Points (LangGraph workflow definition)
- Multi-Component Orchestration
- Core Domain Focus

**Sequence Flow:**
- External System
  - -> `src/agent/graph.py` (`workflow.ainvoke`): Receives `InputState` (adventure description, difficulty, chapters)
    - `src/agent/graph.py`
      - -> `src/agent/utils/prompt_improver.py` (`PromptImproverAgent.run`): Improves initial prompt
      - -> `src/agent/utils/editor_selector.py` (`EditorSelectorAgent.run`): Selects editors
      - -> `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`): Conducts interviews
      - -> `src/agent/utils/outliner.py` (`OutlinerAgent.run_initial_outliner`): Drafts adventure outline
      - -> `src/agent/utils/table_of_content_agent.py` (`TableOfContentAgent.run_writing_table_of_content`): Generates TOC
      - -> `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`): Writes sections, statblocks, items
      - -> `src/agent/utils/publisher_agent.py` (`PublisherAgent.run`): Publishes the final document
      - <- Updates `OutlineState` at each step
    - <- `src/agent/graph.py`: Returns final `OutlineState`

### 2. Prompt Improvement
This workflow refines an initial adventure idea into a more detailed and actionable prompt for subsequent generation steps.

**Main Components:**
- `src/agent/utils/prompt_improver.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/prompt_improver.py` (`PromptImproverAgent.run`): Receives `InputState`
    - `src/agent/utils/prompt_improver.py`
      - -> `PromptImproverAgent.execute` (`self.prompt | self.model`): Invokes LLM with initial idea
      - <- Returns improved prompt string
    - <- `src/agent/utils/prompt_improver.py`: Updates `OutlineState` with `improved_prompt`
- `src/agent/graph.py`

### 3. Editor Selection and Subject Survey
This workflow identifies related subjects for an improved prompt and generates personas for "editors" who will participate in an interview process.

**Main Components:**
- `src/agent/utils/editor_selector.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/tools.py`

**Relevance:**
- Core Domain Focus
- Critical External Integrations (WikipediaRetriever)
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/editor_selector.py` (`EditorSelectorAgent.run`): Receives `OutlineState` with `improved_prompt`
    - `src/agent/utils/editor_selector.py`
      - -> `EditorSelectorAgent.survey_subjects` (`self.generate_idea`): Generates related topics using LLM
      - -> `EditorSelectorAgent.survey_subjects` (`WikipediaRetriever.abatch`): Retrieves documents from Wikipedia
      - -> `EditorSelectorAgent.generate_editor` (`self.model.with_structured_output(Perspectives)`): Generates editor personas based on idea and retrieved docs
      - <- Returns a list of `Editor` objects
    - <- `src/agent/utils/editor_selector.py`: Updates `OutlineState` with `editors`
- `src/agent/graph.py`

### 4. Interview Question Generation
This workflow generates interview questions from an "InterviewQuestionAgent" based on the current interview state and editor persona.

**Main Components:**
- `src/agent/utils/interview_graph.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`)
  - -> `src/agent/utils/interview_graph.py` (`InterviewQuestionAgent.generate_question`): Receives `InterviewState`
    - `src/agent/utils/interview_graph.py` (`InterviewQuestionAgent.generate_question`)
      - -> `self.prompt | self.model`: Invokes LLM to generate a question
      - <- Returns an `AIMessage` containing the question
    - <- `src/agent/utils/interview_graph.py` (`InterviewQuestionAgent.generate_question`): Updates `InterviewState` with the new message
- `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`)

### 5. Interview Answer Generation with Citations
This workflow generates answers to interview questions, potentially using external search tools, and includes citations for the information.

**Main Components:**
- `src/agent/utils/interview_graph.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/tools.py`

**Relevance:**
- Core Domain Focus
- Critical External Integrations (TavilySearch)
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`)
  - -> `src/agent/utils/interview_graph.py` (`InterviewAnswerAgent.run`): Receives `InterviewState` with a question
    - `src/agent/utils/interview_graph.py` (`InterviewAnswerAgent.run`)
      - -> `InterviewAnswerAgent.gen_queries_chain`: Invokes LLM to generate search queries
      - -> `InterviewAnswerAgent.discuss_engine` (`TavilySearch`): Executes search queries
      - -> `InterviewAnswerAgent.gen_answer_chain` (`self.prompt | self.model.with_structured_output(AnswerWithCitations)`): Invokes LLM to generate an answer with citations
      - <- Returns an `AIMessage` containing the answer and cited URLs
    - <- `src/agent/utils/interview_graph.py` (`InterviewAnswerAgent.run`): Updates `InterviewState` with the new message
- `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`)

### 6. Interview Summary Generation
This workflow summarizes the entire interview log for a specific editor, extracting key information.

**Main Components:**
- `src/agent/utils/interview_graph.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`): After all interviews are complete
    - `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`)
      - -> `InterviewSummaryAgent.generate_summary` (`self.prompt | self.model`): Invokes LLM with the full interview log
      - <- Returns a summary string
    - <- `src/agent/utils/interview_graph.py` (`InterviewAgent.run_interview`): Updates `OutlineState` with `interview_summary`
- `src/agent/graph.py`

### 7. Initial Adventure Outline Drafting
This workflow generates the high-level structure of the adventure, including chapters and their synopses, based on the improved prompt and interview summaries.

**Main Components:**
- `src/agent/utils/outliner.py`
- `src/agent/utils/state.py`
- `src/agent/utils/schema/outline_schema.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/writer_agent.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/outliner.py` (`OutlinerAgent.run_initial_outliner`): Receives `OutlineState`
    - `src/agent/utils/outliner.py`
      - -> `OutlinerAgent.draft_outline` (`self.prompt | self.model.with_structured_output(AdventureOutline)`): Invokes LLM to generate `AdventureOutline`
      - -> `OutlinerAgent.run_writing_outline_text` (`self.writer_agent.run_writing_text`): Converts the structured outline to markdown text
      - <- Returns the structured outline and its markdown representation
    - <- `src/agent/utils/outliner.py`: Updates `OutlineState` with `outline_data` and `outline_text`
- `src/agent/graph.py`

### 8. Table of Content Generation
This workflow generates a detailed table of contents, including chapters, characters, and items, based on the initial adventure outline and interview summaries.

**Main Components:**
- `src/agent/utils/table_of_content_agent.py`
- `src/agent/utils/state.py`
- `src/agent/utils/schema/section_schema.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/table_of_content_agent.py` (`TableOfContentAgent.run_writing_table_of_content`): Receives `OutlineState`
    - `src/agent/utils/table_of_content_agent.py`
      - -> `TableOfContentAgent.run_writing_table_of_content_detail` (`self.prompt | self.model.with_structured_output(TableOfContent)`): Invokes LLM to generate `TableOfContent`
      - <- Returns the structured table of contents
    - <- `src/agent/utils/table_of_content_agent.py`: Updates `OutlineState` with `table_of_contents`
- `src/agent/graph.py`

### 9. Section Outline Commenting
This workflow reviews a chapter outline and provides comments or recommendations for improvement.

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`SectionOutlineCommenterAgent.run_comment_section_outline`): Receives `SectionImproverState` with a chapter outline
    - `src/agent/utils/section_writer_agent.py` (`SectionOutlineCommenterAgent.run_comment_section_outline`)
      - -> `self.prompt | self.model`: Invokes LLM to generate comments on the outline
      - <- Returns a list of comment strings
    - <- `src/agent/utils/section_writer_agent.py` (`SectionOutlineCommenterAgent.run_comment_section_outline`): Updates `SectionImproverState` with `comment`
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 10. Section Outline Improvement
This workflow takes a chapter outline and comments, then generates an improved version of the outline.

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/state.py`
- `src/agent/utils/schema/section_schema.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`SectionImproverAgent.run_improving_section_outline`): Receives `SectionImproverState` with outline and comments
    - `src/agent/utils/section_writer_agent.py` (`SectionImproverAgent.run_improving_section_outline`)
      - -> `self.prompt | self.model.with_structured_output(Chapter)`: Invokes LLM to generate an improved `Chapter` outline
      - <- Returns the improved `Chapter` object
    - <- `src/agent/utils/section_writer_agent.py` (`SectionImproverAgent.run_improving_section_outline`): Updates `SectionImproverState` with the improved outline
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 11. Subsection Text Writing
This workflow generates the detailed narrative content for a specific subsection of a chapter.

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/writer_agent.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`SubSectionWriterAgent.run_writing_subsection_text`): Receives `SectionTextState` with subsection details
    - `src/agent/utils/section_writer_agent.py` (`SubSectionWriterAgent.run_writing_subsection_text`)
      - -> `self.writer_agent.run_writing_text` (`self.prompt | self.model`): Invokes LLM to generate subsection text
      - <- Returns the generated text
    - <- `src/agent/utils/section_writer_agent.py` (`SubSectionWriterAgent.run_writing_subsection_text`): Updates `SectionTextState` with the content
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 12. Subsection Text Commenting
This workflow reviews the generated text for a subsection and provides comments or recommendations for improvement.

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/state.py`
- `src/agent/utils/nodes.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`SubSectionCommenterAgent.run_comment_subsection_text`): Receives `SectionTextState` with subsection text
    - `src/agent/utils/section_writer_agent.py` (`SubSectionCommenterAgent.run_comment_subsection_text`)
      - -> `self.prompt | self.model`: Invokes LLM to generate comments on the text
      - <- Returns a list of comment strings
    - <- `src/agent/utils/section_writer_agent.py` (`SubSectionCommenterAgent.run_comment_subsection_text`): Updates `SectionTextState` with `comment`
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 13. Statblock Content Writing
This workflow generates the detailed statblock content for a character (monster or NPC).

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/schema/statblock_schema.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/writer_agent.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`StatblockWriterAgent.run_writing_statblock_text`): Receives `Character` object and difficulty
    - `src/agent/utils/section_writer_agent.py` (`StatblockWriterAgent.run_writing_statblock_text`)
      - -> `self.writer_agent.run_writing_text` (`self.prompt | self.model`): Invokes LLM to generate statblock text using `MarkdownExampleKey.STATBLOCK`
      - <- Returns the generated statblock text
    - <- `src/agent/utils/section_writer_agent.py` (`StatblockWriterAgent.run_writing_statblock_text`): Returns the statblock text to the caller
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 14. Item Content Writing
This workflow generates the detailed description and features for an item.

**Main Components:**
- `src/agent/utils/section_writer_agent.py`
- `src/agent/utils/schema/item_schema.py`
- `src/agent/utils/nodes.py`
- `src/agent/utils/writer_agent.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)
  - -> `src/agent/utils/section_writer_agent.py` (`ItemWriterAgent.run_writing_item_text`): Receives item name and description
    - `src/agent/utils/section_writer_agent.py` (`ItemWriterAgent.run_writing_item_text`)
      - -> `self.writer_agent.run_writing_text` (`self.prompt | self.model`): Invokes LLM to generate item text using `MarkdownExampleKey.ITEM`
      - <- Returns the generated item text
    - <- `src/agent/utils/section_writer_agent.py` (`ItemWriterAgent.run_writing_item_text`): Returns the item text to the caller
- `src/agent/utils/section_writer_agent.py` (`SectionWriterAgent.run_writing_subsection_text_parallel`)

### 15. Full Document Content Assembly
This workflow gathers all generated sections, statblocks, and items, and assembles them into a single, coherent markdown document.

**Main Components:**
- `src/agent/utils/publisher_agent.py`
- `src/agent/utils/state.py`

**Relevance:**
- Core Domain Focus
- Multi-Component Orchestration

**Sequence Flow:**
- `src/agent/graph.py`
  - -> `src/agent/utils/publisher_agent.py` (`PublisherAgent.run`): Receives `OutlineState` containing all generated content
    - `src/agent/utils/publisher_agent.py`
      - -> `PublisherAgent.generate_full_content`: Iterates through `section_texts`, `statblocks`, and `items` from `OutlineState`
      - -> Concatenates all content into a single markdown string
      - <- Returns the complete markdown layout string
    - <- `src/agent/utils/publisher_agent.py`: Passes the layout string to `write_report_by_formats`
- `src/agent/graph.py`

### 16. Markdown File Writing
This utility workflow writes a given text content to a Markdown file.

**Main Components:**
- `src/agent/utils/file_formats.py`

**Relevance:**
- Major Data Operations

**Sequence Flow:**
- Any Agent (e.g., `PublisherAgent`)
  - -> `src/agent/utils/file_formats.py` (`write_text_to_md`): Receives text and a path
    - `src/agent/utils/file_formats.py` (`write_text_to_md`)
      - -> `os.path.dirname`: Ensures directory exists
      - -> `aiofiles.open`: Asynchronously writes text to a `.md` file
      - <- Returns the file path
    - <- Calling Agent: Receives the file path
- Any Agent

### 17. JSON File Writing
This utility workflow writes a given dictionary content to a JSON file.

**Main Components:**
- `src/agent/utils/file_formats.py`

**Relevance:**
- Major Data Operations

**Sequence Flow:**
- Any Agent (e.g., `PublisherAgent`)
  - -> `src/agent/utils/file_formats.py` (`write_json`): Receives a dictionary and a path
    - `src/agent/utils/file_formats.py` (`write_json`)
      - -> `os.path.dirname`: Ensures directory exists
      - -> `json.dumps`: Serializes dictionary to JSON string
      - -> `aiofiles.open`: Asynchronously writes JSON string to a `.json` file
      - <- Returns the file path
    - <- Calling Agent: Receives the file path
- Any Agent

### 18. Markdown to PDF Conversion
This utility workflow converts Markdown text into a PDF document.

**Main Components:**
- `src/agent/utils/file_formats.py`

**Relevance:**
- Major Data Operations

**Sequence Flow:**
- Any Agent (e.g., `PublisherAgent`)
  - -> `src/agent/utils/file_formats.py` (`write_md_to_pdf`): Receives Markdown text and a path
    - `src/agent/utils/file_formats.py` (`write_md_to_pdf`)
      - -> `mistune.html`: Converts Markdown to HTML
      - -> (External PDF conversion tool, not directly shown in provided code): Converts HTML to PDF
      - <- Returns the encoded file path of the PDF
    - <- Calling Agent: Receives the encoded file path
- Any Agent

### 19. Markdown to Word Conversion
This utility workflow converts Markdown text into a DOCX (Word) document.

**Main Components:**
- `src/agent/utils/file_formats.py`

**Relevance:**
- Major Data Operations

**Sequence Flow:**
- Any Agent (e.g., `PublisherAgent`)
  - -> `src/agent/utils/file_formats.py` (`write_md_to_word`): Receives Markdown text and a path
    - `src/agent/utils/file_formats.py` (`write_md_to_word`)
      - -> `mistune.html`: Converts Markdown to HTML
      - -> `Document()`: Creates a new Word document
      - -> (External HTML to DOCX conversion logic, not directly shown in provided code): Converts HTML to DOCX format
      - -> `doc.save`: Saves the DOCX document
      - <- Returns the encoded file path of the DOCX
    - <- Calling Agent: Receives the encoded file path
- Any Agent

### 20. Markdown to Azure Blob Upload
This utility workflow uploads Markdown text to Azure Blob Storage.

**Main Components:**
- `src/agent/utils/file_formats.py`

**Relevance:**
- Major Data Operations
- Critical External Integrations (Azure Blob Storage)

**Sequence Flow:**
- Any Agent (e.g., `PublisherAgent`)
  - -> `src/agent/utils/file_formats.py` (`write_md_to_azure_blob`): Receives Markdown text, connection string, container name, and optional blob name
    - `src/agent/utils/file_formats.py` (`write_md_to_azure_blob`)
      - -> `BlobServiceClient.from_connection_string`: Creates a blob service client
      - -> `container_client.get_container_client`: Gets the container client
      - -> `container_client.create_container`: Ensures container exists
      - -> `container_client.get_blob_client`: Gets the blob client
      - -> `blob_client.upload_blob`: Uploads the text as a blob
      - <- Returns the URL of the uploaded blob
    - <- Calling Agent: Receives the blob URL
- Any Agent
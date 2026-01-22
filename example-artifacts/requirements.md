# Enable GPT-5 Family Models with Downgrade Capability

## Overview

Extend the model configuration system to support OpenAI's GPT-5 family models (gpt-5.2-nano and gpt-5.2-mini) while preserving the ability to use existing GPT-4 models. This enables users to leverage newer models while maintaining a fallback option to proven GPT-4 variants.

## Problem Statement

The current system only supports two GPT-4.1 model variants (`gpt-4.1-nano` and `gpt-4.1-mini`). Users need access to newer GPT-5 family models for improved performance while retaining the ability to downgrade to GPT-4 models when needed. The existing model selection mechanism should be extended rather than replaced to minimize code changes.

## Requirements

### Model Support

- Add support for GPT-5.2 nano and mini models using official OpenAI model names that LangChain supports
- Maintain support for existing GPT-4.1-nano and GPT-4.1-mini models
- Default model should be from the GPT-5 family (specific variant to be determined from OpenAI documentation)
- Keep existing model validation behavior (raise ValueError for unsupported models)

### Configuration System


### Hardcoded Model References

- Update hardcoded `gpt-4.1-mini` references to `gpt-5-mini` in agent classes:
  - `OutlinerAgent`: WriterAgent instantiation
  - `TableOfContentAgent`: _get_model() call
  - `SubSectionWriterAgent`: WriterAgent instantiation
- Ensure each agent upgrades to its GPT-5 equivalent (nano→nano, mini→mini)
- Maintain the same model tier relationships (agents using mini continue using mini)

- Extend the `_get_model()` function in `src/agent/utils/nodes.py` to handle new model names
- Update the `Configuration` TypedDict in `src/agent/graph.py` to include new model options in the Literal type
- Maintain existing configuration mechanism (currently uses `model_name` parameter with default value)
- Preserve LRU cache with maxsize=4 (sufficient for current use case)

### Technical Constraints

- Minimize code changes to existing agent classes (PromptImproverAgent, OutlinerAgent, WriterAgent, etc.)
- Maintain backward compatibility with existing model instantiation patterns
- Keep temperature=0 for deterministic outputs
- Preserve existing API key handling through environment variables

## Open Questions

- **Official GPT-5 Model Names**: What are the exact model identifiers for GPT-5.2 nano and mini as documented in OpenAI's API? (User requested: "check the official documentation for me")
- **Current Configuration Mechanism**: How is model selection currently triggered at runtime? (User indicated: "not sure what is the current indicator is")
- **Default Model Selection**: Which specific GPT-5 variant should be the default? (User specified: "gpt 5 family model" but not which variant)

## Out of Scope

- Changes to model temperature or other generation parameters
- Modifications to the LRU cache size (keeping at 4)
- Changes to error handling behavior (keeping strict validation)
- Addition of environment variables for model configuration
- Support for models outside the GPT-4.1 and GPT-5.2 families

## Acceptance Criteria

**Given** the system is configured with a GPT-5.2 model name  
**When** an agent initializes and calls `_get_model()`  
**Then** a ChatOpenAI instance with the GPT-5.2 model is returned

**Given** the system is configured with a GPT-4.1 model name  
**When** an agent initializes and calls `_get_model()`  
**Then** a ChatOpenAI instance with the GPT-4.1 model is returned (backward compatibility)

**Given** an unsupported model name is provided  
**When** `_get_model()` is called  
**Then** a ValueError is raised with a descriptive error message

**Given** the Configuration TypedDict is updated  
**When** the LangGraph workflow is initialized  
**Then** the new model options are available for selection

**Given** multiple agents use different model configurations  
**When** models are instantiated  
**Then** the LRU cache optimizes repeated model creation (up to 4 configurations)
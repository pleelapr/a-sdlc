# Task 2: Extend _get_model() function to support GPT-5 models

**Dependencies:** Task 1

### Goal
Extend the `_get_model()` factory function to instantiate GPT-5 family models while maintaining backward compatibility with existing GPT-4 models and preserving the LRU cache optimization.

### Implementation Context
**Files to Modify:**
- `src/agent/utils/nodes.py`

**Key Requirements:**
- Add conditional branches for `gpt-5-nano` and `gpt-5-mini` model names
- Maintain existing logic for `gpt-4.1-nano` and `gpt-4.1-mini`
- Keep temperature=0 for deterministic outputs across all models
- Preserve LRU cache with maxsize=4
- Maintain ValueError for unsupported model names
- Keep existing API key handling (environment variable or parameter)

**Technical Notes:**
- Current implementation uses if-elif-else chain for model selection
- LRU cache key is based on (model_name, openai_api_key) tuple
- ChatOpenAI is imported from langchain_openai
- API key is set via os.environ modification (current pattern to maintain)
- Uses existing pattern: `ChatOpenAI(temperature=0, model_name="...")`

**Simplicity Decisions:**
- Maintaining simple if-elif-else pattern rather than dictionary mapping because we only have 4 models total
- Keeping LRU cache at maxsize=4 (sufficient for 4 model configurations)

### Scope Definition
**Deliverables:**
- Two new conditional branches in _get_model() for GPT-5 models
- Consistent ChatOpenAI instantiation pattern across all models
- Updated error message listing all supported models

**Exclusions:**
- No changes to cache size (keeping at 4)
- No changes to temperature parameter (keeping at 0)
- No changes to API key handling mechanism
- No changes to agent classes that call _get_model()

### Implementation Steps
1. Locate the `_get_model()` function in `src/agent/utils/nodes.py`
2. Add new elif branch for `gpt-5-nano`:
   ```python
   elif model_name == "gpt-5-nano":
       model = ChatOpenAI(temperature=0, model_name="gpt-5-nano")
   ```
3. Add new elif branch for `gpt-5-mini`:
   ```python
   elif model_name == "gpt-5-mini":
       model = ChatOpenAI(temperature=0, model_name="gpt-5-mini")
   ```
4. Update the ValueError message in the else clause to list all four supported models
5. Verify the @lru_cache decorator remains unchanged with maxsize=4
6. **Test: Model instantiation with GPT-5 nano**
   - **Setup:** Call _get_model with model_name="gpt-5-nano"
   - **Action:** Function executes
   - **Expect:** Returns ChatOpenAI instance configured for gpt-5-nano with temperature=0
7. **Test: Model instantiation with GPT-5 mini**
   - **Setup:** Call _get_model with model_name="gpt-5-mini"
   - **Action:** Function executes
   - **Expect:** Returns ChatOpenAI instance configured for gpt-5-mini with temperature=0
8. **Test: Backward compatibility with GPT-4 models**
   - **Setup:** Call _get_model with model_name="gpt-4.1-nano"
   - **Action:** Function executes
   - **Expect:** Returns ChatOpenAI instance as before (no regression)
9. **Test: Invalid model name handling**
   - **Setup:** Call _get_model with model_name="gpt-3.5-turbo"
   - **Action:** Function executes
   - **Expect:** Raises ValueError with updated message listing all supported models

### Success Criteria
- _get_model() successfully instantiates all four model variants
- LRU cache continues to work with maxsize=4
- ValueError raised for unsupported models with clear error message
- All existing GPT-4 model instantiation continues to work
- Temperature remains at 0 for all models
- All tests pass

### Scope Constraint
Implement only the _get_model() function changes. Do not modify agent classes, default model selection, or configuration system.
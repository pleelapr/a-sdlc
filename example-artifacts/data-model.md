# Data Model
Data persistence is primarily handled through a PostgreSQL database, with Redis used for caching and session management. The application leverages Pydantic models to define the structure and validation of data, which are then processed within a LangGraph agent workflow.

## Entity Breakdown

### AdventureOutline

**Purpose:**
This entity defines the high-level structure and synopsis of an entire adventure, including its name, number of chapters, and overall story.

**Key Attributes:**
*   `adventure_name` (str): name of the adventure, required
*   `number_of_chapters` (int): number of chapters, required
*   `story_synopsis` (str): synopsis of the adventure, required
*   `chapter_list` (List[Chapter]): list of chapters, required

**Relationships:**
*   One-to-many with `Chapter`

### ChapterDetail

**Purpose:**
This entity provides detailed information for a specific chapter within an adventure, including its synopsis and a list of encounters.

**Key Attributes:**
*   `chapter_no` (str): number of the chapter, required
*   `chapter_name` (str): name of the chapter, required
*   `chapter_synopsis` (str): synopsis of the chapter, required
*   `chapter_encounters` (List[EncounterDetail]): list of encounters in the chapter, required

**Relationships:**
*   Many-to-one with `AdventureOutline`
*   One-to-many with `EncounterDetail`

### EncounterDetail

**Purpose:**
This entity describes the specifics of an encounter within a chapter, detailing its objectives, setting, participants, and potential outcomes.

**Key Attributes:**
*   `encounter_no` (str): number of the encounter, required
*   `encounter_name` (str): name of the encounter, required
*   `encounter_objectives` (List[str]): objectives of the encounter, required
*   `encounter_setting` (str): setting of the encounter, required
*   `encounter_detail` (str): detail of the encounter, required
*   `encounter_location` (List[str]): location of the encounter, required
*   `encounter_active_npcs` (List[str]): active NPCs in the encounter, required
*   `encounter_monsters` (List[EncounterMonster]): monsters in the encounter, required
*   `encounter_traps` (List[str]): traps in the encounter, required
*   `encounter_treasures` (List[str]): treasures in the encounter, required

**Relationships:**
*   Many-to-one with `ChapterDetail`
*   One-to-many with `EncounterMonster`

### EncounterMonster

**Purpose:**
This entity specifies a monster participating in an encounter, including its name, quantity, and whether it is a boss.

**Key Attributes:**
*   `monster_name` (str): name of the monster, required
*   `number_of_monster` (str): number of the monster, required
*   `is_monster_boss` (bool): is the monster a boss?, required

**Relationships:**
*   Many-to-one with `EncounterDetail`

### Location

**Purpose:**
This entity defines a specific location within the adventure, providing its narrative, role, and a list of areas it contains.

**Key Attributes:**
*   `location_name` (str): name of the location, required
*   `location_narrative` (str): describe the location with at least 200 words, required
*   `chapter_no` (int): chapter number that the location is in, required
*   `chapter_name` (str): chapter name that the location is in, required
*   `additional_narrative` (str): additional narrative of the location, required
*   `location_role` (str): role and importance of the location, required
*   `area_list` (List[Area]): list of areas in the location, required

**Relationships:**
*   One-to-many with `Area`

### Area

**Purpose:**
This entity describes a specific area within a location, including its narrative and key investigation points or skill checks.

**Key Attributes:**
*   `area_name` (str): name of the area, required
*   `area_narrative` (str): describe the area with at least 200 words, required
*   `area_keys` (List[AreaKey]): list of key investigation or skill checks of the area, required

**Relationships:**
*   Many-to-one with `Location`
*   One-to-many with `AreaKey`

### AreaKey

**Purpose:**
This entity defines a key investigation or skill check within an area, detailing its name, skill check, difficulty class, description, and outcomes.

**Key Attributes:**
*   `area_key_name` (str): name of the area key, required
*   `area_key_skill_check` (Optional[str]): skill check of the area key, optional
*   `area_key_dc` (Optional[str]): DC of the area key, optional
*   `area_key_description` (str): description of the area key, required
*   `area_key_success_outcome` (str): success outcome of the area key, required
*   `area_key_failure_outcome` (str): failure outcome of the area key, required

**Relationships:**
*   Many-to-one with `Area`

### Item

**Purpose:**
This entity describes an item found in the adventure, including its type, rarity, appearance, and special features.

**Key Attributes:**
*   `item_name` (str): name of the item, required
*   `item_type` (str): type of the item, required
*   `attunement_requirement` (str): attunement requirement of the item, required
*   `rarity` (str): rarity of the item, required
*   `physical_appearance` (str): physical appearance of the item, required
*   `item_description` (str): description of the item, required
*   `item_narrative` (str): narrative of the item, required
*   `item_founded_location` (str): location where the item is founded, required
*   `item_backstory` (str): backstory of the item, required
*   `features` (List[ItemFeature]): features of the item, required

**Relationships:**
*   One-to-many with `ItemFeature`

### ItemFeature

**Purpose:**
This entity defines a specific feature of an item, including its name and description.

**Key Attributes:**
*   `feature_name` (str): name of the item feature, required
*   `feature_description` (str): description of the item feature, required

**Relationships:**
*   Many-to-one with `Item`

### CharacterBase

**Purpose:**
This entity serves as a base class for characters, providing common attributes like physical appearance, alignment, stat block, and combat-related statistics.

**Key Attributes:**
*   `description` (str): high-level description, required
*   `physical_apperance` (str): physical appearance description, required
*   `alignment` (str): alignment e.g. lawful good, chaotic evil, required
*   `size` (str): size e.g. medium, large, huge, gargantuan, required
*   `stat_block` (StatBlock): stat block, required
*   `saving_throws` (List[str]): saving throws, required
*   `armor_class` (str): armor class, required
*   `speed` (List[str]): speed, required
*   `hp` (str): hit points, required
*   `challenge` (str): challenge rating or CR (from 0 to 30), required

**Relationships:**
*   One-to-one with `StatBlock`
*   One-to-many with `Action`
*   One-to-many with `Feats`
*   One-to-many with `Spell`

### Monster

**Purpose:**
This entity defines a monster, inheriting base character attributes and adding monster-specific details like type and boss mechanics.

**Key Attributes:**
*   `monster_name` (str): name of the monster, required
*   `monster_type` (str): type of the monster, required
*   `boss_mechanic` (Optional[List[BossMechanic]]): boss mechanic, optional

**Relationships:**
*   Many-to-one with `CharacterBase`
*   One-to-many with `BossMechanic`

### NPC

**Purpose:**
This entity defines a Non-Player Character (NPC), inheriting base character attributes and adding NPC-specific details like type, race, and roleplaying information.

**Key Attributes:**
*   `character_name` (str): name of the character, required
*   `npc_type` (str): type of the npc, required
*   `npc_race` (str): race of the npc, required
*   `roleplaying` (str): roleplaying of the npc, required

**Relationships:**
*   Many-to-one with `CharacterBase`

### StatBlock

**Purpose:**
This entity holds the core ability scores and modifiers for a character or monster.

**Key Attributes:**
*   `strength` (str): strength with modifier, required
*   `dexterity` (str): dexterity with modifier, required
*   `constitution` (str): constitution with modifier, required
*   `intelligence` (str): intelligence with modifier, required
*   `wisdom` (str): wisdom with modifier, required
*   `charisma` (str): charisma with modifier, required

**Relationships:**
*   One-to-one with `CharacterBase`

### Action

**Purpose:**
This entity describes an action that a character or monster can perform, including its name and a detailed description.

**Key Attributes:**
*   `action_name` (str): name of the action, required
*   `action_description` (str): description of the action, required

**Relationships:**
*   Many-to-one with `CharacterBase`

### TableOfContent

**Purpose:**
This entity represents the overall table of contents for the adventure, listing all chapters, characters, and items.

**Key Attributes:**
*   `chapter_list` (List[Chapter]): List of chapters in the book, required
*   `character_list` (List[Character]): List of characters in the book, required
*   `item_list` (List[Item]): List of items in the book, required

**Relationships:**
*   One-to-many with `Chapter` (from section_schema)
*   One-to-many with `Character` (from section_schema)
*   One-to-many with `Item` (from section_schema)

## Additional Entities
*   `Spell`
*   `Feats`
*   `BossMechanic`
*   `SubSection`
*   `SubSectionList`
*   `RelatedSubjects`
*   `Editor`
*   `Perspectives`
*   `Summary`
*   `AnswerWithCitations`
*   `AnswerWithoutCitations`
*   `Queries`
*   `StatBlockList`
*   `InputState`
*   `OutlineState`
*   `OutputState`
*   `SectionImproverState`
*   `SectionTextState`
*   `Configuration`
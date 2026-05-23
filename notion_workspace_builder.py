#!/usr/bin/env python3
"""
Notion Ultimate Writer Workspace Builder
=========================================
Builds a complete, fully structured Notion writing workspace modelled after
the Oliver Notion Ultimate Writer Planner.

SETUP
-----
1. Go to https://www.notion.so/my-integrations and create a new integration.
2. Copy the "Internal Integration Token" (starts with "secret_...").
3. Open Notion, create or choose a page where the workspace will live.
4. Click ••• → Connections → Add your integration to that page.
5. Copy the page ID from the URL:
      notion.so/<workspace>/<PAGE_ID>?v=...
   The page ID is the 32-character hex string (with or without hyphens).
6. Install the dependency:
      pip install notion-client
7. Run:
      NOTION_TOKEN="secret_xxx" NOTION_PARENT_ID="your-page-id" python notion_workspace_builder.py

WHAT GETS BUILT
---------------
  🏠  Home / Dashboard        — Styled cover page, navigation links, Start Here guide
  👤  Character Builder       — Full character database (gallery-ready) with profile templates
  🌍  Worldbuilding Hub       — WHO / WHAT / WHERE / WHEN / WHY / HOW universe framework
  📍  Locations Tracker       — Location database with maps, atmosphere, linked characters
  📋  Plot Outline            — Premise, story framework, scene DB, chapter planner, arc tracker
  📖  Manuscript              — Cover page, table of contents, chapters, drafts space
  💡  Braindump & Ideas       — Quick-capture idea database with tagging and promotion flow
  📝  Notes & Notions         — Freewrite, research, highlights, sticky reminders
  📅  Writing Planner         — Session log, goals, milestones, word-count tracker
  🔄  Continuity Tracker      — Canon log, contradiction catcher, key-rules reference

MANUAL STEPS AFTER RUNNING
---------------------------
  1. Open the Characters database → switch from Table to Gallery view
     → in Gallery settings, set the card image to the "Portrait" property
  2. Open the Locations database → switch to Gallery view
  3. Add a banner/cover image to the Home page (click "Add cover")
  4. Replace every instance of "[YOUR STORY TITLE]" with your actual title
  5. Customise colours and icons to match your story's aesthetic
"""

import os
import sys
import time
from notion_client import Client
from notion_client.errors import APIResponseError


# ═══════════════════════════════════════════════════════════════
#  RICH TEXT HELPERS
# ═══════════════════════════════════════════════════════════════

def rt(text: str, bold=False, italic=False, code=False, color="default") -> dict:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": {
            "bold": bold, "italic": italic,
            "strikethrough": False, "underline": False,
            "code": code, "color": color,
        },
    }


def rt_mention(page_id: str) -> dict:
    return {"type": "mention", "mention": {"type": "page", "page": {"id": page_id}}}


# ═══════════════════════════════════════════════════════════════
#  BLOCK FACTORIES
# ═══════════════════════════════════════════════════════════════

def h1(text: str) -> dict:
    return {"object": "block", "type": "heading_1",
            "heading_1": {"rich_text": [rt(text)]}}


def h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [rt(text)]}}


def h3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [rt(text)]}}


def p(*parts) -> dict:
    """Paragraph accepting plain strings or pre-built rich-text dicts."""
    rich = []
    for part in parts:
        if isinstance(part, str):
            rich.append(rt(part))
        elif isinstance(part, dict):
            rich.append(part)
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich}}


def div() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def callout(text: str, emoji: str = "💡", color: str = "yellow_background") -> dict:
    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": [rt(text)],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": color,
        },
    }


def bul(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [rt(text)]}}


def num(text: str) -> dict:
    return {"object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": [rt(text)]}}


def qblock(text: str) -> dict:
    return {"object": "block", "type": "quote",
            "quote": {"rich_text": [rt(text, italic=True)]}}


def toggle(text: str, children: list = None) -> dict:
    return {
        "object": "block", "type": "toggle",
        "toggle": {
            "rich_text": [rt(text, bold=True)],
            "children": children or [],
        },
    }


def toc() -> dict:
    return {"object": "block", "type": "table_of_contents",
            "table_of_contents": {"color": "default"}}


# ═══════════════════════════════════════════════════════════════
#  DATABASE PROPERTY SCHEMA HELPERS
# ═══════════════════════════════════════════════════════════════

_PALETTE = ["blue", "green", "purple", "orange", "yellow", "pink", "red", "gray", "brown"]


def _opts(*names) -> list:
    return [{"name": n, "color": _PALETTE[i % len(_PALETTE)]} for i, n in enumerate(names)]


def prop_title() -> dict:      return {"title": {}}
def prop_text() -> dict:       return {"rich_text": {}}
def prop_num() -> dict:        return {"number": {"format": "number"}}
def prop_date() -> dict:       return {"date": {}}
def prop_check() -> dict:      return {"checkbox": {}}
def prop_url() -> dict:        return {"url": {}}
def prop_files() -> dict:      return {"files": {}}


def prop_sel(*opts) -> dict:
    return {"select": {"options": _opts(*opts)}}


def prop_msel(*opts) -> dict:
    return {"multi_select": {"options": _opts(*opts)}}


def prop_relation(db_id: str) -> dict:
    return {"relation": {"database_id": db_id}}


# ═══════════════════════════════════════════════════════════════
#  WORKSPACE BUILDER
# ═══════════════════════════════════════════════════════════════

class WorkspaceBuilder:

    def __init__(self, token: str, parent_id: str):
        self.n = Client(auth=token)
        self.root = parent_id.replace("-", "").strip()
        self.ids: dict[str, str] = {}   # label → page id
        self.dbs: dict[str, str] = {}   # label → database id
        self._delay = 0.4               # seconds between API calls

    # ──────────────────────────────────────────────
    #  Core API wrappers
    # ──────────────────────────────────────────────

    def _pause(self):
        time.sleep(self._delay)

    def _create_page(self, parent_id: str, title: str,
                     emoji: str = None, cover: str = None,
                     children: list = None) -> str:
        payload = {
            "parent": {"page_id": parent_id},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        if emoji:    payload["icon"] = {"type": "emoji", "emoji": emoji}
        if cover:    payload["cover"] = {"type": "external", "external": {"url": cover}}
        if children: payload["children"] = children[:100]

        try:
            resp = self.n.pages.create(**payload)
            pid = resp["id"]
            if children and len(children) > 100:
                self._append(pid, children[100:])
            self._pause()
            return pid
        except APIResponseError as exc:
            print(f"  ✗  Error creating page '{title}': {exc}")
            raise

    def _create_db(self, parent_id: str, title: str, props: dict,
                   emoji: str = None, inline: bool = True) -> str:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": props,
            "is_inline": inline,
        }
        if emoji: payload["icon"] = {"type": "emoji", "emoji": emoji}

        try:
            resp = self.n.databases.create(**payload)
            did = resp["id"]
            self._pause()
            return did
        except APIResponseError as exc:
            print(f"  ✗  Error creating database '{title}': {exc}")
            raise

    def _db_item(self, db_id: str, props: dict,
                 children: list = None, emoji: str = None) -> str:
        payload = {"parent": {"database_id": db_id}, "properties": props}
        if emoji:    payload["icon"] = {"type": "emoji", "emoji": emoji}
        if children: payload["children"] = children[:100]
        try:
            resp = self.n.pages.create(**payload)
            pid = resp["id"]
            if children and len(children) > 100:
                self._append(pid, children[100:])
            self._pause()
            return pid
        except APIResponseError as exc:
            print(f"  ✗  Error creating db item: {exc}")
            raise

    def _append(self, block_id: str, blocks: list):
        for i in range(0, len(blocks), 100):
            try:
                self.n.blocks.children.append(block_id=block_id, children=blocks[i:i + 100])
                self._pause()
            except APIResponseError as exc:
                print(f"  ✗  Error appending blocks: {exc}")
                raise

    def _update_db(self, db_id: str, props: dict):
        try:
            self.n.databases.update(database_id=db_id, properties=props)
            self._pause()
        except APIResponseError as exc:
            print(f"  ✗  Error updating database: {exc}")
            raise

    # ──────────────────────────────────────────────
    #  Property value helpers
    # ──────────────────────────────────────────────

    def _pv_title(self, text: str) -> dict:
        return {"title": [{"type": "text", "text": {"content": text}}]}

    def _pv_text(self, text: str) -> dict:
        return {"rich_text": [{"type": "text", "text": {"content": text}}]}

    def _pv_sel(self, name: str) -> dict:
        return {"select": {"name": name}}

    def _pv_msel(self, *names) -> dict:
        return {"multi_select": [{"name": n} for n in names]}

    def _pv_num(self, n) -> dict:
        return {"number": n}

    def _pv_date(self, iso: str) -> dict:
        return {"date": {"start": iso}}

    def _pv_check(self, v: bool) -> dict:
        return {"checkbox": v}

    # ──────────────────────────────────────────────
    #  Build orchestrator
    # ──────────────────────────────────────────────

    def build(self):
        print("🚀  Notion Ultimate Writer Workspace Builder")
        print("─" * 52)

        print("\n📁  Creating section hub pages …")
        self._make_section_pages()

        print("\n📊  Creating databases …")
        self._make_databases()

        print("\n✍️   Seeding template entries …")
        self._seed_databases()

        print("\n🔗  Linking databases (relations) …")
        self._add_relations()

        print("\n📄  Building page content …")
        self._build_all_page_content()

        print("\n🏠  Building home/dashboard …")
        self._build_home_page()

        print("\n" + "═" * 52)
        print("✅  WORKSPACE COMPLETE!")
        home = self.ids.get("home", "")
        print(f"\n🔗  Open: https://notion.so/{home.replace('-', '')}")
        print("\n📌  Finish up in Notion:")
        print("    1. Characters DB → Gallery view → set 'Portrait' as card cover")
        print("    2. Locations DB  → Gallery view")
        print("    3. Home page     → click 'Add cover' and upload your banner art")
        print("    4. Search & replace '[YOUR STORY TITLE]' with your actual title")
        print("    5. Customise icons, colours, and section order as you like")

    # ──────────────────────────────────────────────
    #  Section pages
    # ──────────────────────────────────────────────

    def _make_section_pages(self):
        sections = [
            ("characters_hub", "👤 Character Builder",    "👤"),
            ("worldbuilding",  "🌍 Worldbuilding Hub",    "🌍"),
            ("locations_hub",  "📍 Locations Tracker",    "📍"),
            ("plot_outline",   "📋 Plot Outline",          "📋"),
            ("manuscript",     "📖 Manuscript",            "📖"),
            ("braindump",      "💡 Braindump & Ideas",     "💡"),
            ("notes",          "📝 Notes & Notions",       "📝"),
            ("planner",        "📅 Writing Planner",       "📅"),
            ("continuity",     "🔄 Continuity Tracker",   "🔄"),
        ]
        for key, title, emoji in sections:
            pid = self._create_page(self.root, title, emoji)
            self.ids[key] = pid
            print(f"    ✓  {title}")

    # ──────────────────────────────────────────────
    #  Databases (no relations yet)
    # ──────────────────────────────────────────────

    def _make_databases(self):
        # ── Characters ──────────────────────────
        self.dbs["characters"] = self._create_db(
            self.ids["characters_hub"], "Characters",
            {
                "Name":       prop_title(),
                "Role":       prop_sel("Protagonist", "Antagonist", "Supporting",
                                       "Minor", "Mentor", "Villain", "Anti-Hero"),
                "Importance": prop_sel("Major", "Secondary", "Minor", "Background"),
                "Status":     prop_sel("Active", "Deceased", "Unknown", "Transformed"),
                "Age":        prop_num(),
                "Story Arc":  prop_sel("Ongoing", "Complete", "Tragic",
                                       "Redemptive", "Flat", "Coming of Age"),
                "Tags":       prop_msel("Heroic", "Morally Grey", "Mentor",
                                        "Comic Relief", "Unreliable", "Mysterious"),
                "Portrait":   prop_files(),
                "Notes":      prop_text(),
            },
            emoji="👤",
        )
        print("    ✓  Characters")

        # ── Locations ───────────────────────────
        self.dbs["locations"] = self._create_db(
            self.ids["locations_hub"], "Locations",
            {
                "Name":         prop_title(),
                "Type":         prop_sel("City", "Town", "Village", "Building",
                                         "Wilderness", "Dungeon", "Region",
                                         "Planet", "Landmark", "Other"),
                "Significance": prop_sel("Major", "Secondary", "Minor", "Background"),
                "Region":       prop_text(),
                "Atmosphere":   prop_text(),
                "Tags":         prop_msel("Urban", "Rural", "Dangerous", "Sacred",
                                          "Hidden", "Ancient", "Modern"),
                "Map / Image":  prop_files(),
            },
            emoji="📍",
        )
        print("    ✓  Locations")

        # ── Scenes ──────────────────────────────
        self.dbs["scenes"] = self._create_db(
            self.ids["plot_outline"], "Scenes",
            {
                "Scene Title":    prop_title(),
                "Chapter #":      prop_num(),
                "Scene Order":    prop_num(),
                "Emotional Beat": prop_sel("Hook", "Rising Tension", "Climax",
                                           "Falling Action", "Resolution", "Twist",
                                           "Revelation", "Rest", "Loss",
                                           "Humor", "Confrontation"),
                "Plot Purpose":   prop_text(),
                "Status":         prop_sel("Idea", "Outlined", "Drafted",
                                           "Written", "Revised", "Final"),
                "Word Count":     prop_num(),
                "Tags":           prop_msel("Action", "Dialogue", "Description",
                                            "Emotional", "World-building", "Exposition"),
            },
            emoji="🎬",
        )
        print("    ✓  Scenes")

        # ── Chapters ────────────────────────────
        self.dbs["chapters"] = self._create_db(
            self.ids["manuscript"], "Chapters",
            {
                "Chapter Title": prop_title(),
                "Chapter #":     prop_num(),
                "Status":        prop_sel("Not Started", "Outlined", "Drafted",
                                          "Revised", "Final"),
                "Word Count":    prop_num(),
                "Summary":       prop_text(),
                "Notes":         prop_text(),
            },
            emoji="📖",
        )
        print("    ✓  Chapters")

        # ── Ideas / Braindump ────────────────────
        self.dbs["ideas"] = self._create_db(
            self.ids["braindump"], "Ideas & Braindump",
            {
                "Title":         prop_title(),
                "Type":          prop_sel("Character Idea", "Plot Idea", "World Idea",
                                          "Dialogue", "Setting", "Theme",
                                          "Scene", "Other"),
                "Status":        prop_sel("Raw", "Developing", "Promoted", "Archived"),
                "Priority":      prop_sel("High", "Medium", "Low"),
                "Date Captured": prop_date(),
                "Tags":          prop_msel("Urgent", "Inspired", "Random",
                                           "Dream", "What If", "Overheard"),
                "Notes":         prop_text(),
            },
            emoji="💡",
        )
        print("    ✓  Ideas & Braindump")

        # ── Writing Sessions ─────────────────────
        self.dbs["sessions"] = self._create_db(
            self.ids["planner"], "Writing Sessions Log",
            {
                "Session":            prop_title(),
                "Date":               prop_date(),
                "Words Written":      prop_num(),
                "Project Area":       prop_sel("Characters", "World", "Plot",
                                               "Manuscript", "Planning",
                                               "Research", "Editing"),
                "Mood":               prop_sel("🔥 Productive", "✅ Good",
                                               "😐 Okay", "😓 Struggling",
                                               "🧱 Blocked"),
                "What I Worked On":   prop_text(),
                "Reflection":         prop_text(),
                "What To Fix Next":   prop_text(),
            },
            emoji="📅",
        )
        print("    ✓  Writing Sessions Log")

        # ── Milestones ───────────────────────────
        self.dbs["milestones"] = self._create_db(
            self.ids["planner"], "Milestones",
            {
                "Milestone":   prop_title(),
                "Target Date": prop_date(),
                "Completed":   prop_check(),
                "Category":    prop_sel("First Draft", "Revision", "Worldbuilding",
                                        "Character Work", "Research", "Publishing"),
                "Notes":       prop_text(),
            },
            emoji="🏆",
        )
        print("    ✓  Milestones")

        # ── Canon Log ────────────────────────────
        self.dbs["canon"] = self._create_db(
            self.ids["continuity"], "Canon Log",
            {
                "Fact":        prop_title(),
                "Category":    prop_sel("Character", "World Rules", "Magic System",
                                        "Timeline", "Relationship",
                                        "Location", "Plot", "Other"),
                "Status":      prop_sel("Confirmed Canon", "Potential Issue",
                                        "Contradiction", "Under Review", "Retconned"),
                "Description": prop_text(),
                "Tags":        prop_msel("Critical", "Major", "Minor", "Background"),
            },
            emoji="📜",
        )
        print("    ✓  Canon Log")

        # ── World Elements ───────────────────────
        self.dbs["world_elements"] = self._create_db(
            self.ids["worldbuilding"], "World Elements",
            {
                "Element":      prop_title(),
                "Dimension":    prop_sel(
                    "WHO — Peoples & Factions",
                    "WHAT — Systems & Culture",
                    "WHERE — Geography & Places",
                    "WHEN — History & Timeline",
                    "WHY — Origins & Myths",
                    "HOW — Power & Governance",
                ),
                "Sub-Category": prop_text(),
                "Status":       prop_sel("Draft", "Developing", "Established", "Canon"),
                "Tags":         prop_msel("Core Lore", "Magic", "Political",
                                          "Religious", "Economic", "Military", "Cultural"),
                "Notes":        prop_text(),
            },
            emoji="🌍",
        )
        print("    ✓  World Elements")

    # ──────────────────────────────────────────────
    #  Relations (added after all DBs exist)
    # ──────────────────────────────────────────────

    def _add_relations(self):
        char_id  = self.dbs["characters"]
        loc_id   = self.dbs["locations"]
        chap_id  = self.dbs["chapters"]
        canon_id = self.dbs["canon"]
        scene_id = self.dbs["scenes"]

        self._update_db(scene_id, {
            "POV Character": prop_relation(char_id),
            "Location":      prop_relation(loc_id),
            "Chapter Link":  prop_relation(chap_id),
        })
        print("    ✓  Scenes ↔ Characters, Locations, Chapters")

        self._update_db(loc_id, {
            "Characters": prop_relation(char_id),
        })
        print("    ✓  Locations ↔ Characters")

        self._update_db(canon_id, {
            "Characters": prop_relation(char_id),
            "Locations":  prop_relation(loc_id),
        })
        print("    ✓  Canon Log ↔ Characters, Locations")

    # ──────────────────────────────────────────────
    #  Seed data / template entries
    # ──────────────────────────────────────────────

    def _seed_databases(self):
        self._seed_characters()
        self._seed_locations()
        self._seed_scenes()
        self._seed_chapters()
        self._seed_ideas()
        self._seed_milestones()
        self._seed_canon()
        self._seed_world_elements()
        print("    ✓  All template entries added")

    # ── Character full-page template ─────────────

    def _char_template_blocks(self) -> list:
        return [
            callout(
                "This is your character profile. Every section is a toggle — click to expand. "
                "Replace all placeholder text with your character's details.",
                "👤", "blue_background",
            ),
            div(),
            h1("🖼️ Portrait & Reference Art"),
            p("Upload or embed your character portrait and full reference art below."),
            p("[Upload portrait image — this will show as the gallery card cover]"),
            div(),
            toggle("📐 Physical Description", [
                p("Age: "),
                p("Height / Build: "),
                p("Hair colour & style: "),
                p("Eye colour: "),
                p("Skin tone: "),
                p("Distinguishing features / scars / marks: "),
                p("General appearance notes: "),
                div(),
                p("[Full character art / reference sheet — embed image here]"),
            ]),
            toggle("🧠 Personality", [
                h3("Strengths"),
                bul("[Strength 1]"),
                bul("[Strength 2]"),
                bul("[Strength 3]"),
                h3("Flaws"),
                bul("[Flaw 1]"),
                bul("[Flaw 2]"),
                h3("Quirks"),
                bul("[Quirk 1]"),
                h3("Fears"),
                bul("[Fear 1]"),
                h3("Desires / Core Want"),
                bul("[What does this character most deeply want?]"),
                h3("Core Wound / Lie They Believe"),
                p("[What false belief about themselves or the world drives their behaviour?]"),
            ]),
            toggle("📜 Backstory & Origin", [
                p("Where did this character come from? What shaped them before the story begins?"),
                p(""),
                h3("Key Events Before the Story"),
                bul("[Event 1]"),
                bul("[Event 2]"),
                h3("Family & Relationships (Pre-Story)"),
                p(""),
            ]),
            toggle("🌱 Character Arc", [
                h3("Where They Start (Beginning of Story)"),
                p("[Describe their internal state, worldview, and behaviour at the opening]"),
                h3("Key Turning Points"),
                bul("[First major shift — what happens and how they change]"),
                bul("[Second major shift]"),
                bul("[Climactic moment]"),
                h3("Where They End (By Story's Close)"),
                p("[Describe how they've grown, broken, or transformed]"),
                h3("Arc Type"),
                p("□ Growth arc   □ Fall arc   □ Redemption arc   □ Flat arc   □ Tragic arc"),
            ]),
            toggle("🤝 Relationships", [
                callout(
                    "Link other character pages using @ mentions. "
                    "Use the 'Characters' relation property in the sidebar to connect them.",
                    "🔗", "gray_background",
                ),
                h3("Key Relationships"),
                p("[Character name] — [nature of relationship] — [dynamic / tension]"),
                p("[Character name] — [nature of relationship] — [dynamic / tension]"),
                h3("Relationship Arc"),
                p("[How do their key relationships change over the course of the story?]"),
            ]),
            toggle("🗣️ Dialogue Voice & Speech Patterns", [
                p("Formal or casual? Accent or dialect? Vocabulary level?"),
                p("Things they always say / catchphrases: "),
                p("Things they never say / forbidden words: "),
                p("How they express anger: "),
                p("How they express affection: "),
                div(),
                h3("Sample Dialogue"),
                qblock('"[Write a line of dialogue that perfectly captures their voice]"'),
                qblock('"[Another sample — perhaps under stress or in conflict]"'),
            ]),
            toggle("📌 Key Facts & Canon Details", [
                callout(
                    "Keep this list updated! "
                    "These are the facts that must stay consistent throughout your story.",
                    "⚠️", "red_background",
                ),
                bul("[Fact 1 — e.g. 'Is left-handed']"),
                bul("[Fact 2 — e.g. 'Cannot swim']"),
                bul("[Fact 3 — e.g. 'Allergic to X']"),
                bul("[Fact 4 — e.g. 'Birthday is in the winter']"),
                bul("[Add more as you write — keep every established detail here]"),
            ]),
            toggle("✏️ Notes (Freeform)", [
                p("Anything else — half-formed ideas, things to explore, what-ifs, deleted scenes with this character."),
                p(""),
            ]),
        ]

    def _seed_characters(self):
        tmpl = self._char_template_blocks()
        characters = [
            ("[Protagonist Name]",    "Protagonist",  "Major",     "Active",  "Ongoing",        "⭐"),
            ("[Antagonist Name]",     "Antagonist",   "Major",     "Active",  "Ongoing",        "🔴"),
            ("[Mentor / Guide]",      "Mentor",       "Secondary", "Active",  "Flat",           "🟡"),
            ("[Supporting Character]","Supporting",   "Secondary", "Active",  "Coming of Age",  "🟢"),
            ("[Minor Character]",     "Minor",        "Minor",     "Active",  "Flat",           "⚪"),
        ]
        for name, role, importance, status, arc, emoji in characters:
            self._db_item(
                self.dbs["characters"],
                {
                    "Name":       self._pv_title(name),
                    "Role":       self._pv_sel(role),
                    "Importance": self._pv_sel(importance),
                    "Status":     self._pv_sel(status),
                    "Story Arc":  self._pv_sel(arc),
                },
                children=tmpl,
                emoji=emoji,
            )

    # ── Location full-page template ───────────────

    def _loc_template_blocks(self) -> list:
        return [
            callout(
                "Fill in the details for this location. Make it vivid — what does it look, "
                "feel, smell, and sound like?",
                "📍", "green_background",
            ),
            div(),
            h2("🗺️ Overview"),
            p("Type: "),
            p("Region / Country / World Area: "),
            p("Significance to Story: "),
            div(),
            h2("👁️ Sensory Description"),
            p("Visual — what do you see?"),
            p(""),
            p("Sound — what do you hear?"),
            p(""),
            p("Smell — what do you smell?"),
            p(""),
            p("Touch / Temperature — what does it feel like to be here?"),
            p(""),
            h2("🌆 Atmosphere & Tone"),
            p("[What emotion or mood does this place evoke? Oppressive? Peaceful? Eerie? Alive?]"),
            div(),
            h2("👥 Who Lives / Frequents This Place"),
            p("[Who calls this place home? Who visits and why?]"),
            bul("[Character / group name] — [reason for being here]"),
            div(),
            h2("📋 Significance to the Plot"),
            p("[What happens here that matters to the story? Why does this location exist in the narrative?]"),
            div(),
            h2("📖 History & Lore"),
            p("[What is the backstory of this place? What happened here before the events of the story?]"),
            div(),
            h2("🖼️ Map / Image"),
            p("[Embed a map, sketch, or reference image here]"),
            div(),
            h2("✏️ Notes"),
            p(""),
        ]

    def _seed_locations(self):
        tmpl = self._loc_template_blocks()
        locations = [
            ("[Primary Setting — e.g. The Capital City]", "City",      "Major"),
            ("[Secondary Location — e.g. The Old Library]","Building",  "Secondary"),
            ("[Wilderness Area — e.g. The Dark Forest]",  "Wilderness", "Minor"),
            ("[Hidden Location — e.g. The Sanctuary]",    "Landmark",   "Secondary"),
        ]
        for name, typ, sig in locations:
            self._db_item(
                self.dbs["locations"],
                {
                    "Name":         self._pv_title(name),
                    "Type":         self._pv_sel(typ),
                    "Significance": self._pv_sel(sig),
                },
                children=tmpl,
            )

    def _seed_scenes(self):
        scenes = [
            ("Opening Scene — Status Quo",       1, 1, "Hook",           "Introduce the protagonist and the world before the inciting incident.", "Idea"),
            ("Inciting Incident",                1, 2, "Twist",          "The event that disrupts the protagonist's normal world and sets the story in motion.", "Idea"),
            ("First Complication",               2, 3, "Rising Tension", "The protagonist encounters their first real obstacle.", "Idea"),
            ("Midpoint Shift",                   2, 4, "Twist",          "A revelation or reversal that raises the stakes and changes the story's direction.", "Idea"),
            ("Dark Night of the Soul",           3, 5, "Loss",           "The protagonist's lowest point — all seems lost.", "Idea"),
            ("Climax",                           3, 6, "Climax",         "The final confrontation where the protagonist faces the central conflict.", "Idea"),
            ("Resolution",                       3, 7, "Resolution",     "The aftermath — how the world and characters have changed.", "Idea"),
        ]
        for title, chap, order, beat, purpose, status in scenes:
            self._db_item(
                self.dbs["scenes"],
                {
                    "Scene Title":    self._pv_title(title),
                    "Chapter #":      self._pv_num(chap),
                    "Scene Order":    self._pv_num(order),
                    "Emotional Beat": self._pv_sel(beat),
                    "Plot Purpose":   self._pv_text(purpose),
                    "Status":         self._pv_sel(status),
                },
            )

    # ── Chapter full-page template ────────────────

    def _chapter_template_blocks(self, number: int) -> list:
        return [
            callout(
                "Chapter Notes live above the divider. Your prose lives below. "
                "Keep planning separate from writing.",
                "✍️", "gray_background",
            ),
            h2("📋 Chapter Notes"),
            p("POV Character: "),
            p("Primary Location: "),
            p("Time in Story: "),
            p("Chapter Goal — what must change by the end of this chapter?"),
            p(""),
            h3("Scenes in This Chapter"),
            bul("[Scene 1 — brief description]"),
            bul("[Scene 2 — brief description]"),
            h3("Emotional Arc"),
            p("Opens feeling: "),
            p("Shifts through: "),
            p("Closes feeling: "),
            h3("What Changes"),
            p("[What is different about the world or the characters at the end vs. the beginning?]"),
            div(),
            h1(f"Chapter {number}"),
            div(),
            p(""),
            p("[Your prose begins here…]"),
            p(""),
            p(""),
        ]

    def _seed_chapters(self):
        for i in range(1, 4):
            self._db_item(
                self.dbs["chapters"],
                {
                    "Chapter Title": self._pv_title(f"Chapter {i}"),
                    "Chapter #":     self._pv_num(i),
                    "Status":        self._pv_sel("Not Started"),
                    "Word Count":    self._pv_num(0),
                },
                children=self._chapter_template_blocks(i),
            )

    def _seed_ideas(self):
        import datetime
        today = datetime.date.today().isoformat()
        ideas = [
            ("What if the antagonist's motivation is entirely sympathetic?",       "Plot Idea",     "High"),
            ("A scene where the protagonist confronts the thing they fear most",   "Scene",         "High"),
            ("The magic system might have an unexpected cost that changes everything","World Idea",  "High"),
            ("Overheard: 'You never asked the right question.'",                   "Dialogue",      "Medium"),
            ("What if two characters who seem opposed want the same thing?",       "Plot Idea",     "Medium"),
            ("A location that feels wrong — safe on the surface but deeply off",   "Setting",       "Low"),
            ("The theme of the whole story in a single image",                     "Theme",         "Low"),
        ]
        for title, typ, priority in ideas:
            self._db_item(
                self.dbs["ideas"],
                {
                    "Title":         self._pv_title(title),
                    "Type":          self._pv_sel(typ),
                    "Status":        self._pv_sel("Raw"),
                    "Priority":      self._pv_sel(priority),
                    "Date Captured": self._pv_date(today),
                },
            )

    def _seed_milestones(self):
        milestones = [
            ("World & character outlines complete",       "Worldbuilding"),
            ("Full plot outline complete",                "First Draft"),
            ("Chapter 1 written",                         "First Draft"),
            ("25% of first draft written",                "First Draft"),
            ("50% of first draft written",                "First Draft"),
            ("First draft complete",                      "First Draft"),
            ("First revision pass complete",              "Revision"),
            ("Beta readers consulted",                    "Revision"),
            ("Second revision pass complete",             "Revision"),
            ("Final draft ready",                         "Revision"),
        ]
        for title, cat in milestones:
            self._db_item(
                self.dbs["milestones"],
                {
                    "Milestone": self._pv_title(title),
                    "Completed": self._pv_check(False),
                    "Category":  self._pv_sel(cat),
                },
            )

    def _seed_canon(self):
        canon = [
            (
                "[Magic Rule 1 — e.g. 'Magic cannot create life']",
                "Magic System", "Confirmed Canon",
                "A core rule of the magic system. Established in the opening chapters.",
            ),
            (
                "[Timeline — e.g. 'The story opens in Year 0 AR (After the Reckoning)']",
                "Timeline", "Confirmed Canon",
                "The world uses its own calendar system.",
            ),
            (
                "[Character Fact — e.g. 'Protagonist cannot read']",
                "Character", "Confirmed Canon",
                "Established in chapter 1. Must remain consistent.",
            ),
            (
                "[World Rule — e.g. 'The sun sets in the north']",
                "World Rules", "Confirmed Canon",
                "A physical quirk of this world. Don't contradict it.",
            ),
            (
                "[Add your first confirmed fact here]",
                "Other", "Confirmed Canon", "",
            ),
        ]
        for fact, cat, status, desc in canon:
            self._db_item(
                self.dbs["canon"],
                {
                    "Fact":        self._pv_title(fact),
                    "Category":    self._pv_sel(cat),
                    "Status":      self._pv_sel(status),
                    "Description": self._pv_text(desc),
                },
            )

    def _seed_world_elements(self):
        elements = [
            ("The Peoples of the World",         "WHO — Peoples & Factions",     "Species / Races"),
            ("Major Factions & Organizations",   "WHO — Peoples & Factions",     "Factions"),
            ("Class Structure & Social Order",   "WHO — Peoples & Factions",     "Society"),
            ("The Magic System",                 "WHAT — Systems & Culture",     "Magic"),
            ("Technology & Tools",               "WHAT — Systems & Culture",     "Technology"),
            ("Economy, Trade & Currency",        "WHAT — Systems & Culture",     "Economy"),
            ("Religion & Belief Systems",        "WHAT — Systems & Culture",     "Religion"),
            ("Language, Script & Communication", "WHAT — Systems & Culture",     "Language"),
            ("Art, Music & Storytelling",        "WHAT — Systems & Culture",     "Arts"),
            ("Food, Clothing & Daily Life",      "WHAT — Systems & Culture",     "Culture"),
            ("World Geography & Continents",     "WHERE — Geography & Places",   "Geography"),
            ("Major Cities & Settlements",       "WHERE — Geography & Places",   "Locations"),
            ("Natural Wonders & Landmarks",      "WHERE — Geography & Places",   "Landmarks"),
            ("The Creation of the World",        "WHEN — History & Timeline",    "Prehistory"),
            ("Major Historical Eras",            "WHEN — History & Timeline",    "History"),
            ("Wars & Conflicts",                 "WHEN — History & Timeline",    "Conflict"),
            ("Events Preceding the Story",       "WHEN — History & Timeline",    "Recent History"),
            ("Creation Myth & Cosmology",        "WHY — Origins & Myths",        "Mythology"),
            ("The Nature of Gods & Powers",      "WHY — Origins & Myths",        "Theology"),
            ("Origin of Magic / Technology",     "WHY — Origins & Myths",        "Origin"),
            ("The Central Drive of Society",     "WHY — Origins & Myths",        "Philosophy"),
            ("Political Systems & Governance",   "HOW — Power & Governance",     "Politics"),
            ("Laws, Justice & Punishment",       "HOW — Power & Governance",     "Law"),
            ("Military Structure & Power",       "HOW — Power & Governance",     "Military"),
            ("Ecosystems & Natural Laws",        "HOW — Power & Governance",     "Nature"),
        ]
        for name, dim, sub in elements:
            self._db_item(
                self.dbs["world_elements"],
                {
                    "Element":      self._pv_title(name),
                    "Dimension":    self._pv_sel(dim),
                    "Sub-Category": self._pv_text(sub),
                    "Status":       self._pv_sel("Draft"),
                },
            )

    # ──────────────────────────────────────────────
    #  Page content (intro blocks for each hub)
    # ──────────────────────────────────────────────

    def _build_all_page_content(self):
        self._build_characters_hub()
        self._build_worldbuilding_hub()
        self._build_locations_hub()
        self._build_plot_outline()
        self._build_manuscript()
        self._build_braindump()
        self._build_notes()
        self._build_planner()
        self._build_continuity()
        print("    ✓  All section content built")

    def _build_characters_hub(self):
        self._append(self.ids["characters_hub"], [
            callout(
                "Your master character database. Every person in your story — from protagonist "
                "to background face — belongs here. Click any character card to open their full profile.",
                "👤", "blue_background",
            ),
            div(),
            h2("📖 How to Use"),
            bul("Click '+ New' to add a character — fill in the sidebar properties first (Role, Importance, etc.)"),
            bul("Switch from Table to Gallery view (top-right) for visual character cards"),
            bul("In Gallery settings → Card preview → set 'Portrait' as the card image"),
            bul("Inside each character page: expand the toggles and fill every section"),
            bul("Use filters to view only Protagonists, only Major characters, etc."),
            bul("Relate characters to Scenes via the 'POV Character' property in the Scenes database"),
            div(),
            h2("🔍 Suggested Views"),
            bul("Gallery by Role — see all your protagonists, antagonists, and supporting cast at a glance"),
            bul("Filter: Importance = Major — focus on the characters who drive the story"),
            bul("Filter: Status = Deceased — keep track of who's gone"),
            div(),
            callout(
                "TIP: The Characters database below is also visible. "
                "Switch it to Gallery view and pin the Portrait property as the card cover.",
                "💡", "yellow_background",
            ),
        ])

    def _build_worldbuilding_hub(self):
        self._append(self.ids["worldbuilding"], [
            callout(
                "Your complete universe lives here. Build every layer — who inhabits the world, "
                "what systems govern it, where events unfold, when history unfolded, why the world "
                "is the way it is, and how it all functions.",
                "🌍", "green_background",
            ),
            div(),
            h1("The World at a Glance"),
            p("[Add a one-paragraph overview of your world here — its name, its feel, its central tension.]"),
            div(),
            h2("👥 WHO — Peoples, Races, Factions & Organizations"),
            p("Who populates this world? What groups, species, civilisations, and factions exist?"),
            bul("Races and species — what beings are there, and how do they differ?"),
            bul("Cultures and peoples — distinct human (or non-human) cultures"),
            bul("Factions, guilds, orders — organisations with agendas"),
            bul("Social classes — who holds power and who doesn't"),
            bul("Secret societies and underground groups"),
            div(),
            h2("⚙️ WHAT — Systems, Culture & Knowledge"),
            p("What are the building blocks of this world's reality?"),
            bul("Magic system — rules, costs, abilities, limitations, who can use it and why"),
            bul("Technology — what exists, what doesn't, how advanced is society"),
            bul("Economy — currency, trade routes, resources, wealth distribution"),
            bul("Religion and belief systems — gods, clergy, heresies, cults, creation stories"),
            bul("Art, music, food, clothing — the texture of daily life"),
            bul("Language and script — names, idioms, written systems"),
            div(),
            h2("📍 WHERE — Geography & The Physical World"),
            p("Where does the story take place? Explore the physical shape of your world."),
            bul("Continents, kingdoms, territories, and political borders"),
            bul("Major cities, towns, villages, and settlements"),
            bul("Natural landmarks — mountains, forests, seas, deserts, rivers"),
            bul("Hidden or mystical locations — ruins, sanctuaries, dimensional spaces"),
            p("[Embed your world map image here]"),
            div(),
            h2("📅 WHEN — History, Timeline & Eras"),
            p("When did things happen? Build the history that shaped your world into what it is today."),
            bul("The world's origin and pre-history"),
            bul("Major historical eras and their defining characteristics"),
            bul("Wars, catastrophes, golden ages, and turning points"),
            bul("The founding of key nations, religions, and institutions"),
            bul("The events that directly precede the story"),
            div(),
            h2("💫 WHY — Origins, Myths & Driving Forces"),
            p("Why does this world exist the way it does? What myths and philosophies underpin it?"),
            bul("Creation myths and cosmology — how did the world come to exist?"),
            bul("The nature of gods, spirits, or higher powers"),
            bul("The origin of magic, technology, or civilisation"),
            bul("What the world fears, worships, or desires collectively"),
            bul("The central ideological conflict driving society"),
            div(),
            h2("⚖️ HOW — Power, Governance & Functioning"),
            p("How does this world actually work on a day-to-day basis?"),
            bul("Political systems — monarchies, republics, theocracies, empires, etc."),
            bul("Laws and justice — what's legal, what's forbidden, how is it enforced"),
            bul("Military structure — armies, guards, private forces, power hierarchies"),
            bul("Ecosystems — flora, fauna, weather patterns, natural laws"),
            bul("Cause-and-effect — how decisions ripple through society"),
            div(),
            h2("📚 World Elements Database"),
            p("Use the World Elements database to log every piece of lore. "
              "Filter by Dimension to focus on one layer at a time."),
        ])

    def _build_locations_hub(self):
        self._append(self.ids["locations_hub"], [
            callout(
                "Every place your story visits — or simply exists in the background — belongs here. "
                "Build rich, sensory locations that feel real enough to walk through.",
                "📍", "green_background",
            ),
            div(),
            h2("📖 How to Use"),
            bul("Add a new location with '+ New' — fill in Type and Significance first"),
            bul("Inside each location page: describe it through all the senses"),
            bul("Link characters who live or frequently visit this location"),
            bul("Link scenes that take place here via the Scenes database relation"),
            bul("Embed maps, sketches, or reference photos in the location's Map / Image property"),
            div(),
            h2("🏷️ Location Types"),
            bul("🏙️  City / Town / Village — populated settlements"),
            bul("🏛️  Building — specific interiors: palaces, taverns, libraries, dungeons"),
            bul("🌲  Wilderness — forests, mountains, seas, plains, deserts"),
            bul("🏔️  Landmark — ruins, monuments, sacred sites, magical locations"),
            bul("🌌  Region / Planet — for speculative or science fiction worlds"),
            div(),
            h2("🔍 Suggested Views"),
            bul("Filter by Significance = Major → the locations that matter most to the plot"),
            bul("Filter by Type → see all your cities, all your wilderness areas, etc."),
            bul("Gallery view → visual reference cards for every location"),
        ])

    def _build_plot_outline(self):
        self._append(self.ids["plot_outline"], [
            callout(
                "The architecture of your story. Plan from the one-line premise all the way "
                "down to scene-by-scene. Link every scene to its chapter, location, and POV character.",
                "📋", "purple_background",
            ),
            div(),
            h1("Story Structure"),
            div(),
            toggle("🎯 Story Premise & Identity", [
                h3("One-Line Pitch / Logline"),
                p("[A single sentence that captures the entire story — who wants what, what stands in their way, and what's at stake]"),
                h3("Core Conflict"),
                p("[What is the central tension? What opposing forces drive the narrative?]"),
                h3("Themes"),
                bul("[Main theme — the central question your story asks]"),
                bul("[Secondary theme]"),
                h3("Tone & Genre"),
                p("[What kind of story is this? What emotion should it leave the reader with?]"),
                h3("Intended Audience"),
                p("[Who is this story for?]"),
            ]),
            div(),
            toggle("📐 Story Framework", [
                callout(
                    "Choose your framework. Three-Act Structure, Hero's Journey, Save the Cat, "
                    "or your own. Fill in whichever fits your story — delete the rest.",
                    "📐", "blue_background",
                ),
                h3("Act One — Setup"),
                p("Opening image / status quo: "),
                p("Inciting incident: "),
                p("First plot point / call to action: "),
                p("Protagonist's initial refusal / hesitation: "),
                h3("Act Two — Confrontation"),
                p("First complication: "),
                p("Midpoint shift / revelation: "),
                p("Escalating obstacles: "),
                p("Dark night of the soul: "),
                p("Second plot point / decision: "),
                h3("Act Three — Resolution"),
                p("Climax — the final confrontation: "),
                p("Falling action: "),
                p("Resolution / denouement: "),
                p("Final image: "),
            ]),
            div(),
            toggle("📈 Conflict & Tension Map", [
                p("Track where tension rises and falls across the story."),
                h3("Low Tension — Rest & Recovery Beats"),
                bul("[Scene or chapter where things breathe]"),
                h3("Medium Tension — Rising Complications"),
                bul("[Scene or chapter where stakes climb]"),
                h3("High Tension — Crises & Climaxes"),
                bul("[Scene or chapter of maximum pressure]"),
                h3("Notes on Pacing"),
                p("[Any overall pacing concerns to keep in mind?]"),
            ]),
            div(),
            toggle("🎭 Character Arc Tracker", [
                p("Map each major character's internal journey alongside the plot."),
                h3("Protagonist Arc"),
                p("Starts as: "),
                p("Changes through: "),
                p("Ends as: "),
                h3("Antagonist Arc"),
                p("Starts as: "),
                p("Changes through: "),
                p("Ends as: "),
                h3("Supporting Character Arcs"),
                p("[Character name] — starts as ___ / ends as ___"),
                p("[Character name] — starts as ___ / ends as ___"),
            ]),
            div(),
            toggle("🔚 Ending Planner", [
                h3("Climax"),
                p("[What is the final confrontation or moment of resolution?]"),
                h3("Resolution"),
                p("[How does the world look after the climax? What has changed?]"),
                h3("Loose Ends to Tie Up"),
                bul("[Thread 1]"),
                bul("[Thread 2]"),
                h3("Themes Paid Off"),
                p("[How does the ending answer the central thematic question?]"),
                h3("Final Image / Last Line"),
                p("[What is the very last thing the reader sees or reads?]"),
            ]),
            div(),
            h2("🎬 Scene-by-Scene Breakdown"),
            p("Every scene in the story lives in the Scenes database below. "
              "Link each scene to its Chapter, POV Character, and Location. "
              "Sort by 'Scene Order' to see the full narrative sequence."),
            div(),
            h2("📖 Chapter Planner"),
            p("Use the Chapters database (in the Manuscript section) to organise scenes into chapters. "
              "Filter scenes by 'Chapter #' to see what's in each chapter."),
        ])

    def _build_manuscript(self):
        # Cover page (child of manuscript hub)
        cover_id = self._create_page(
            self.ids["manuscript"], "📕 Story Cover Page", "📕",
            children=[
                callout(
                    "This is the face of your story. Add your title, tagline, cover art, and description.",
                    "📕", "orange_background",
                ),
                div(),
                h1("[YOUR STORY TITLE]"),
                qblock("[Tagline — a single line that captures the soul of the story]"),
                div(),
                p("[Embed your cover art or illustration here]"),
                div(),
                h2("Story Details"),
                p("Author: "),
                p("Genre: "),
                p("Tone / Mood: "),
                p("Target Word Count: "),
                p("Current Status: "),
                div(),
                h2("Story Description"),
                p("[2–3 paragraphs describing your story — who it follows, what they want, what stands in their way, and what's at stake.]"),
                div(),
                h2("Content Notes"),
                p("[Content warnings, intended audience, age rating, themes explored.]"),
            ],
        )
        self.ids["cover_page"] = cover_id

        # Table of contents
        toc_id = self._create_page(
            self.ids["manuscript"], "📑 Table of Contents", "📑",
            children=[
                callout(
                    "Add a link to each chapter as you create them. "
                    "Use @ to mention chapter pages directly.",
                    "📑", "blue_background",
                ),
                div(),
                h1("[YOUR STORY TITLE]"),
                h2("Table of Contents"),
                div(),
                p("Chapter 1 — [Title]"),
                p("Chapter 2 — [Title]"),
                p("Chapter 3 — [Title]"),
                p("[Continue adding chapters…]"),
                div(),
                callout(
                    "TIP: Once each chapter page exists, come back here and use @ "
                    "to link them so readers (and you) can jump directly to any chapter.",
                    "💡", "yellow_background",
                ),
            ],
        )
        self.ids["toc"] = toc_id

        # Sample chapter pages (standalone pages, not just DB entries)
        for i in range(1, 4):
            cid = self._create_page(
                self.ids["manuscript"],
                f"📄 Chapter {i}",
                "📄",
                children=self._chapter_template_blocks(i),
            )
            self.ids[f"ms_chapter_{i}"] = cid

        # Drafts / discarded writing
        drafts_id = self._create_page(
            self.ids["manuscript"], "🗑️ Drafts & Discarded Writing", "🗑️",
            children=[
                callout(
                    "Nothing is wasted. Store every cut scene, alternate version, "
                    "and discarded passage here. They might come back.",
                    "🗑️", "gray_background",
                ),
                div(),
                h2("How to Use"),
                bul("Before deleting any writing from the manuscript, paste it here first"),
                bul("Label each entry: what it was, where it came from, why it was cut"),
                bul("Date your entries so you know what draft they're from"),
                bul("Mark entries with ✅ when you're truly done with them"),
                div(),
                h2("Alternate Versions"),
                p("[Paste alternate versions of scenes, chapters, or passages here]"),
                div(),
                h2("Cut Scenes"),
                p("[Paste removed scenes here before deleting them]"),
                div(),
                h2("Discarded Lines & Passages"),
                p("[Great lines and paragraphs that didn't fit — keep them]"),
            ],
        )
        self.ids["drafts"] = drafts_id

        # Hub intro content
        self._append(self.ids["manuscript"], [
            callout(
                "This is where the story comes to life. Write your manuscript here, "
                "chapter by chapter. Keep planning notes separate from prose.",
                "📖", "orange_background",
            ),
            div(),
            h2("📚 Manuscript Structure"),
            bul("📕 Story Cover Page — title, tagline, description, cover art"),
            bul("📑 Table of Contents — links to every chapter"),
            bul("📄 Chapter 1, 2, 3… — one page per chapter, write freely inside"),
            bul("🗑️ Drafts & Discarded Writing — a home for cut content"),
            bul("📖 Chapters database (below) — track word counts and status"),
            div(),
            h2("✍️ Writing Guidelines"),
            bul("Each chapter page has two zones: Chapter Notes (planning) above the divider, Prose below"),
            bul("Never delete writing — move it to Drafts first"),
            bul("Update word count in the Chapters database after each session"),
            bul("Use the Writing Planner to log your sessions and track overall progress"),
            div(),
            h2("📊 Chapter Tracker"),
            p("The Chapters database below tracks every chapter's status, word count, and notes."),
        ])

    def _build_braindump(self):
        self._append(self.ids["braindump"], [
            callout(
                "Ideas die when they have nowhere to go. This is your safety net. "
                "Capture everything instantly — no structure, no judgment, no filtering.",
                "💡", "yellow_background",
            ),
            div(),
            h1("Never Lose An Idea"),
            div(),
            h2("⚡ Quick Capture — How to Use"),
            bul("Hit '+ New' in the database below — type the idea title and hit Enter"),
            bul("Tag it by Type so you can find it later (Character Idea, Plot Idea, etc.)"),
            bul("Set Priority (High / Medium / Low) while it's fresh"),
            bul("Add notes in the idea page if the thought needs more room"),
            bul("When an idea is ready to use, change Status to 'Promoted' and link it to the relevant section"),
            bul("Archive ideas you've used or set aside — keep the active list clean"),
            div(),
            callout(
                "🔥  CAPTURE RULE: Never filter yourself here. "
                "Bad ideas are better than lost ideas. Bad ideas lead to good ones.",
                "🔥", "red_background",
            ),
            div(),
            toggle("Quick-Entry Template (copy this for a new idea)", [
                p("Title: [one-line description of the idea]"),
                p("Type: Character Idea / Plot Idea / World Idea / Dialogue / Setting / Theme / Scene / Other"),
                p("Priority: High / Medium / Low"),
                p(""),
                p("Notes:"),
                p("[Expand here — a few sentences is enough. You can always come back.]"),
                p(""),
                p("Links to explore:"),
                bul("[Once promoted, link to the relevant character, scene, or worldbuilding page]"),
            ]),
            div(),
            h2("💡 All Ideas"),
            p("Every idea is in the database below. "
              "Filter by Status to see Raw ideas (your backlog), or by Priority to tackle the urgent ones."),
        ])

    def _build_notes(self):
        self._append(self.ids["notes"], [
            callout(
                "Your thinking space. Freeform, unstructured, and entirely yours. "
                "Use it to think, research, observe, and remember.",
                "📝", "gray_background",
            ),
            div(),
            h1("Notes, Notions & Highlights"),
            div(),
            toggle("✍️ Freewrite Space", [
                callout(
                    "Write to think — not to produce. This space is for process, not output. "
                    "No structure required. No judgment. Just write.",
                    "✍️", "gray_background",
                ),
                p(""),
                p("[Start writing here — any time you need to think something through, open this toggle and write.]"),
                p(""),
            ]),
            div(),
            toggle("💭 Notions — Small Sparks & Observations", [
                p("Small thoughts, observations, half-questions, and creative sparks that don't fit elsewhere."),
                bul("[Notion 1]"),
                bul("[Notion 2]"),
                bul("[Add new ones as they come — date them if useful]"),
            ]),
            div(),
            toggle("🔆 Highlights — Key Insights & Breakthroughs", [
                callout("[Your most important creative insight or breakthrough this week]", "🔆", "yellow_background"),
                callout("[A discovery about your characters or world that changed something]", "⭐", "orange_background"),
                callout("[An insight about your writing process]", "💡", "blue_background"),
                p("Add new highlights using callout blocks with a ⭐, 🔆, or 💡 icon."),
                p("These should be things worth remembering — breakthroughs, revelations, 'aha' moments."),
            ]),
            div(),
            toggle("🔬 Research Notes", [
                p("Reference material, articles, books, films, and real-world research that feeds the story."),
                div(),
                h3("Books & Stories (Reference)"),
                bul("[Title] — [author] — [why it's relevant]"),
                div(),
                h3("Research Topics"),
                bul("[Topic] — [source] — [key notes]"),
                div(),
                h3("Web Links & Resources"),
                bul("[Title or URL] — [what it contains and why it's useful]"),
                div(),
                h3("Real-World Parallels"),
                bul("[Historical event / place / person] — [how it maps onto the story]"),
            ]),
            div(),
            toggle("📌 Sticky Notes & Reminders", [
                callout(
                    "⚠️  CONTINUITY FLAG: [Something that must stay consistent — add details]",
                    "⚠️", "red_background",
                ),
                callout(
                    "🔧  TO FIX: [A plot hole, inconsistency, or unresolved thread to address]",
                    "🔧", "orange_background",
                ),
                callout(
                    "📌  REMEMBER: [Something important to keep in mind while writing]",
                    "📌", "blue_background",
                ),
                callout(
                    "🗓️  REVISIT: [Something to come back to in the next session]",
                    "🗓️", "purple_background",
                ),
                p("Delete reminders once they're resolved. Add new ones using callout blocks."),
            ]),
            div(),
            h2("📓 Open Notes"),
            p("[Add any additional freeform notes, observations, or miscellaneous writing here.]"),
            p(""),
        ])

    def _build_planner(self):
        self._append(self.ids["planner"], [
            callout(
                "Your writing habit and progress hub. "
                "Track every session, measure progress, celebrate milestones, and reflect.",
                "📅", "purple_background",
            ),
            div(),
            h1("Writing Planner & Progress Tracker"),
            div(),
            toggle("🎯 Writing Goals", [
                h3("Daily Goal"),
                p("Words per session: "),
                h3("Weekly Goal"),
                p("Sessions per week:     Target weekly words: "),
                h3("Project Goal"),
                p("Target total word count: "),
                p("Target completion date: "),
                h3("Current Progress"),
                p("Words written so far: "),
                p("Sessions completed this week: "),
                p("Estimated completion at current pace: "),
            ]),
            div(),
            toggle("📊 Overall Progress", [
                callout("Update this after every major session!", "📊", "green_background"),
                p("Chapters complete:         /        total"),
                p("Scenes complete:           /        total"),
                p("Total words written:                "),
                p("Target word count:                  "),
                p("Percentage complete:       %"),
                p("Current draft stage:       □ Planning  □ First Draft  □ Revision  □ Final"),
            ]),
            div(),
            toggle("💡 Writing Habit Tips", [
                bul("Write at the same time every day — even 20 minutes counts"),
                bul("Focus on output, not quality — editing comes later"),
                bul("Log every session: it makes progress visible and keeps you accountable"),
                bul("Celebrate small wins — a chapter outlined is a win"),
                bul("When stuck, write a scene from a different part of the story"),
                bul("Bad writing days are still writing days"),
            ]),
            div(),
            h2("📋 Session Log"),
            p("Log every writing session in the database below. Date, words written, what you worked on, and a quick reflection."),
            div(),
            h2("🏆 Milestones"),
            p("Every major milestone is tracked in the database below. Check them off as you hit them."),
        ])

    def _build_continuity(self):
        self._append(self.ids["continuity"], [
            callout(
                "Consistency is the invisible craft. Every fact about your world, "
                "characters, and story that must stay consistent lives here.",
                "🔄", "red_background",
            ),
            div(),
            h1("Consistency & Continuity Tracker"),
            div(),
            toggle("⚡ Quick Reference — Key Rules", [
                callout(
                    "Keep the most critical consistency rules here for fast reference before each session.",
                    "⚡", "blue_background",
                ),
                h3("Magic System Rules"),
                bul("[Core rule 1]"),
                bul("[Core rule 2 — what magic cannot do]"),
                bul("[Cost or limitation — established in which chapter]"),
                h3("Character Ages at Story Start"),
                p("[Character name]: Age [X] at the opening of the story"),
                p("[Character name]: Age [X] at the opening of the story"),
                h3("Timeline & Calendar"),
                p("Story opens: [year / season / era]"),
                p("Story ends approximately: [year / season / era]"),
                h3("Established World Rules"),
                bul("[Physical or supernatural law that governs this world]"),
                bul("[Social or political fact that's been stated]"),
                bul("[Historical fact referenced in the text]"),
            ]),
            div(),
            toggle("🚨 Contradiction Catcher", [
                callout(
                    "Flag anything here that might conflict with established canon. "
                    "Review this list before each writing session.",
                    "🚨", "red_background",
                ),
                bul("[Chapter X says A, but Chapter Y says B — resolve before continuing]"),
                bul("[Unresolved plot thread that might contradict something]"),
                bul("[Character who acted out of their established personality]"),
                p(""),
                p("[Delete or annotate each item once resolved]"),
            ]),
            div(),
            toggle("📖 In-World Documents", [
                p("Space for in-world artefacts: letters, newspapers, laws, maps, prophecies, historical texts."),
                p("These make the world feel real — write them here and reference them from scene notes."),
                p(""),
                p("[Add in-world documents here — format them as if they were real documents from your world]"),
            ]),
            div(),
            h2("📜 Canon Log Database"),
            p("Every confirmed fact about your story, world, and characters — logged and searchable. "
              "Filter by Category or Status to find what you need."),
        ])

    # ──────────────────────────────────────────────
    #  Home page (built last — links to everything)
    # ──────────────────────────────────────────────

    def _build_home_page(self):
        home_children = [
            # Welcome banner
            callout(
                "Welcome to your writing workspace. Every tool you need to build your world, "
                "develop your characters, plan your story, and write your manuscript — "
                "all in one place. Start here, then go wherever the story calls.",
                "✍️", "blue_background",
            ),
            div(),

            # Title block
            h1("[YOUR STORY TITLE]"),
            qblock("[Tagline — a single sentence that captures the heart of your story]"),
            div(),

            # Navigation
            h2("🧭 Workspace Navigation"),
            p("→ 👤 ", rt_mention(self.ids["characters_hub"]),
              "  —  Character profiles, arcs, relationships, and voice"),
            p("→ 🌍 ", rt_mention(self.ids["worldbuilding"]),
              "  —  Full universe: who, what, where, when, why, and how"),
            p("→ 📍 ", rt_mention(self.ids["locations_hub"]),
              "  —  Every location, map, atmosphere, and setting"),
            p("→ 📋 ", rt_mention(self.ids["plot_outline"]),
              "  —  Story structure, premise, scenes, and chapter planning"),
            p("→ 📖 ", rt_mention(self.ids["manuscript"]),
              "  —  The manuscript itself: cover, table of contents, chapters"),
            p("→ 💡 ", rt_mention(self.ids["braindump"]),
              "  —  Instant idea capture — never lose a thought"),
            p("→ 📝 ", rt_mention(self.ids["notes"]),
              "  —  Freewrite space, research, notions, and sticky reminders"),
            p("→ 📅 ", rt_mention(self.ids["planner"]),
              "  —  Writing sessions, goals, milestones, and progress"),
            p("→ 🔄 ", rt_mention(self.ids["continuity"]),
              "  —  Canon log, continuity tracker, and contradiction catcher"),
            div(),

            # Start Here toggle
            toggle("📌 START HERE — How to Use This Workspace", [
                callout(
                    "Read this once to orient yourself. Then get to work — the system will make sense as you use it.",
                    "📌", "blue_background",
                ),
                div(),
                h2("Getting Started — Recommended Order"),
                num("Set your story's identity: Replace '[YOUR STORY TITLE]' everywhere with your actual title. "
                    "Add a tagline below it."),
                num("Build your world: Open the Worldbuilding Hub and start filling in the WHO, WHAT, and WHERE sections. "
                    "These form the foundation everything else builds on."),
                num("Create your characters: Open Character Builder. Add your protagonist and antagonist first. "
                    "Then fill in their full profile page — don't skip the Character Arc section."),
                num("Map your locations: Add your main settings in the Locations Tracker. "
                    "Link them to characters and scenes as you go."),
                num("Outline your plot: Open the Plot Outline. Write your logline, set up your story framework, "
                    "then build your scene list in the Scenes database."),
                num("Start writing: Move to the Manuscript. Open Chapter 1. Write. "
                    "Keep your chapter notes above the divider, prose below it."),
                num("Log your sessions: After every session, add an entry to the Writing Planner's Session Log. "
                    "Track your word count and leave yourself a reflection note."),
                num("Capture everything: Any time a new idea surfaces — open Braindump and add it immediately. "
                    "Never let an idea go uncaptured."),
                div(),
                h2("Quick Tips"),
                bul("Switch the Characters database to Gallery view for visual character cards"),
                bul("Use @ to link pages across the workspace — characters in scene notes, locations in chapters"),
                bul("Check the Continuity Tracker before each session to stay consistent"),
                bul("The Notes section is for thinking out loud — write freely, don't edit yourself"),
                bul("The Braindump is for capturing — the other sections are for developing"),
                bul("Nothing is locked: rename, move, or restructure anything to fit your workflow"),
                bul("The databases are all interlinked — follow relations to jump between characters, scenes, and locations"),
            ]),
            div(),

            # Story snapshot toggle
            toggle("📖 Story Identity Snapshot", [
                h2("[YOUR STORY TITLE]"),
                qblock("[Tagline]"),
                div(),
                p("Genre: "),
                p("Tone / Mood: "),
                p("Target Word Count: "),
                p("Target Completion Date: "),
                p("Current Draft Stage:   □ Outlining  □ First Draft  □ Revising  □ Final"),
                div(),
                h3("One-Line Pitch (Logline)"),
                p("[Write your logline here — a single sentence that captures the whole story]"),
                div(),
                h3("Story Description"),
                p("[2–3 sentences. Who is the protagonist? What do they want? What stands in their way? What's at stake?]"),
                div(),
                p("[Embed your cover art here]"),
            ]),
            div(),

            # Current status toggle
            toggle("📊 Current Status & What's Next", [
                h3("Right Now"),
                p("Currently working on: "),
                p("Last session date: "),
                p("Words written in last session: "),
                p("Total words so far: "),
                div(),
                h3("Next Session Goals"),
                bul("[Goal 1]"),
                bul("[Goal 2]"),
                div(),
                h3("Blockers / Things to Resolve"),
                bul("[Any plot holes, unanswered questions, or decisions that need to be made]"),
            ]),
            div(),

            # Footer callout
            callout(
                "✨  Every great story starts with a single word. Write something today.",
                "✨", "purple_background",
            ),
        ]

        home_id = self._create_page(
            self.root,
            "✍️ [YOUR STORY TITLE] — Writer's Workspace",
            emoji="✍️",
            children=home_children,
        )
        self.ids["home"] = home_id


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def main():
    token  = os.environ.get("NOTION_TOKEN",    "").strip()
    parent = os.environ.get("NOTION_PARENT_ID","").strip()

    if not token:
        print("❌  NOTION_TOKEN is not set.")
        print("    Create an integration at https://www.notion.so/my-integrations")
        sys.exit(1)

    if not parent:
        print("❌  NOTION_PARENT_ID is not set.")
        print("    Copy the page ID from your Notion page URL (the 32-character hex string).")
        sys.exit(1)

    try:
        WorkspaceBuilder(token, parent).build()
    except APIResponseError as exc:
        print(f"\n❌  Notion API error: {exc}")
        print("    Check your token, page ID, and that the integration has access to the page.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Build interrupted. Some pages may have been created.")
        sys.exit(1)


if __name__ == "__main__":
    main()

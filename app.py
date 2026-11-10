"""Streamlit interface for the grounded Recipe Box assistant."""

from pathlib import Path
import re

import streamlit as st

from recipebot import llm
from recipebot.chat import Bot, Session as BotSession


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "recipes.db"

st.set_page_config(
    page_title="Chef — Recipe Box",
    page_icon="🍲",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #26332d;
        --muted: #758078;
        --green: #245c46;
        --green-dark: #194733;
        --cream: #fbf8f1;
        --line: #e8e8df;
        --orange: #e98f55;
    }
    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        color: var(--ink);
    }
    .stApp {
        background:
            radial-gradient(ellipse at 82% 0%, rgba(232, 241, 226, .64), transparent 34rem),
            var(--cream);
    }
    [data-testid="stHeader"] { background: rgba(251, 248, 241, .82); }
    [data-testid="stSidebar"] {
        background: #f3f1e9;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.1rem; }
    .brand {
        display: flex;
        align-items: center;
        gap: .75rem;
        padding: .3rem .1rem 1.2rem;
    }
    .brand-mark {
        display: grid;
        place-items: center;
        width: 2.8rem;
        height: 2.8rem;
        border-radius: 1rem;
        background: var(--green);
        color: white;
        font-size: 1.35rem;
        box-shadow: 0 7px 18px rgba(36, 92, 70, .18);
    }
    .brand-name { font-weight: 700; font-size: 1.08rem; line-height: 1.2; }
    .brand-caption { color: var(--muted); font-size: .76rem; margin-top: .18rem; }
    .side-label {
        color: #78827a;
        text-transform: uppercase;
        letter-spacing: .12em;
        font-size: .68rem;
        font-weight: 700;
        margin: 1.35rem 0 .55rem;
    }
    .status-card {
        border: 1px solid #e4e6dc;
        background: rgba(255,255,255,.62);
        border-radius: 1rem;
        padding: .85rem .9rem;
        margin: .55rem 0;
    }
    .status-title { font-size: .78rem; color: var(--muted); }
    .status-value { font-weight: 700; font-size: .95rem; margin-top: .2rem; }
    .hero {
        padding: 2rem 0 1.35rem;
        max-width: 760px;
    }
    .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: .4rem;
        border: 1px solid #dfe9dc;
        color: var(--green);
        background: rgba(255,255,255,.72);
        border-radius: 99px;
        padding: .35rem .7rem;
        font-size: .76rem;
        font-weight: 700;
        letter-spacing: .02em;
    }
    .hero h1 {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: clamp(2.35rem, 5vw, 3.7rem);
        line-height: 1.08;
        letter-spacing: -.04em;
        margin: .9rem 0 .6rem;
        color: #20372b;
    }
    .hero p {
        max-width: 610px;
        margin: 0;
        color: #6d786f;
        font-size: 1.03rem;
        line-height: 1.65;
    }
    .welcome-card {
        border: 1px solid #e6e8df;
        background: rgba(255,255,255,.68);
        border-radius: 1.15rem;
        min-height: 9.4rem;
        padding: 1rem 1.05rem;
        margin: .15rem 0 .4rem;
        box-shadow: 0 8px 24px rgba(35, 54, 42, .035);
    }
    .welcome-icon { font-size: 1.3rem; }
    .welcome-title { font-weight: 700; margin: .45rem 0 .25rem; }
    .welcome-copy { color: var(--muted); font-size: .84rem; line-height: 1.45; }
    [data-testid="stChatMessage"] {
        border: 1px solid rgba(226, 229, 220, .88);
        border-radius: 1.15rem;
        padding: .35rem .75rem;
        background: rgba(255,255,255,.7);
        box-shadow: 0 5px 18px rgba(35, 54, 42, .025);
        margin-bottom: .85rem;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        background: #eef4ed;
    }
    [data-testid="stChatInput"] {
        border-color: #dfe4da;
        border-radius: 1.15rem;
        box-shadow: 0 12px 34px rgba(35, 54, 42, .08);
    }
    [data-testid="stChatInput"] textarea { font-family: 'DM Sans', sans-serif; }
    .footnote {
        color: #889189;
        font-size: .75rem;
        text-align: center;
        padding: 1rem 0 2rem;
    }
    div.stButton > button {
        border-radius: .8rem;
        border-color: #dfe5dc;
        color: #365747;
        transition: all .15s ease;
    }
    div.stButton > button:hover {
        border-color: #9ab6a2;
        color: var(--green-dark);
        background: #f2f7f0;
    }
    div.stButton > button[kind="primary"] {
        background: var(--green);
        border-color: var(--green);
    }
    div.stButton > button[kind="primary"]:hover {
        background: var(--green-dark);
        border-color: var(--green-dark);
        color: white;
    }
    @media (max-width: 700px) {
        .hero { padding-top: 1.2rem; }
        .hero h1 { font-size: 2.35rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def start_new_conversation(bot):
    bot.reply("reset")
    st.session_state.recipe_session = bot.s
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    bot.con.close()


def render_message(content):
    """Render the bot's Markdown while preserving intentional plain-text line breaks."""
    formatted = content.replace("\r\n", "\n").replace("\r", "\n")
    formatted = re.sub(r"\s*\[query plan:.*$", "", formatted, flags=re.MULTILINE)
    st.markdown(formatted.replace("\n", "  \n"))


if not DB_PATH.is_file():
    st.error(
        f"Recipe database not found at `{DB_PATH}`. "
        "Build it first with `python -m recipebot.ingest --data-dir data --db data/recipes.db`."
    )
    st.stop()

if "recipe_session" not in st.session_state:
    st.session_state.recipe_session = BotSession()
if "llm_enabled" not in st.session_state:
    st.session_state.llm_enabled = llm.available()
    st.session_state.llm_status = llm.status()

try:
    bot = Bot(str(DB_PATH), use_llm=False)
    bot.s = st.session_state.recipe_session
    bot.use_llm = st.session_state.llm_enabled
    if "recipe_count" not in st.session_state:
        st.session_state.recipe_count = bot.con.execute(
            "SELECT COUNT(*) FROM recipes WHERE is_valid=1 AND dup_of IS NULL"
        ).fetchone()[0]
except Exception as exc:
    st.error(f"Could not open the recipe database: {exc}")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

with st.sidebar:
    st.markdown(
        """
        <div class="brand">
            <div class="brand-mark">🍲</div>
            <div>
                <div class="brand-name">Chef</div>
                <div class="brand-caption">Your Recipe Box assistant</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("＋  New conversation", type="primary", use_container_width=True):
        start_new_conversation(bot)
        st.rerun()

    st.markdown('<div class="side-label">Your recipe box</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="status-card">
            <div class="status-title">Recipes ready to explore</div>
            <div class="status-value">🥗 {st.session_state.recipe_count:,} recipes</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="side-label">Assistant mode</div>', unsafe_allow_html=True)
    if bot.use_llm:
        mode = "AI-assisted · grounded answers"
        detail = st.session_state.llm_status
    else:
        mode = "Reliable recipe mode"
        detail = "Rule-based assistant · no API key needed"
    st.markdown(
        f"""
        <div class="status-card">
            <div class="status-value">🟢 {mode}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(detail)

    st.markdown('<div class="side-label">Try asking</div>', unsafe_allow_html=True)
    examples = [
        ("🔎  Find a recipe", "Find a penne pasta recipe."),
        ("📊  Explore the data", "How many recipes contain both garlic and onion?"),
        ("🧺  Match my ingredients", "I have eggs, onions, tomatoes, and rice. Suggest five recipes, no peanuts."),
        ("♻️  Adapt a recipe", "Replace cream in this penne recipe without dairy."),
    ]
    for index, (label, prompt) in enumerate(examples):
        if st.button(label, key=f"example_{index}", use_container_width=True):
            st.session_state.pending_prompt = prompt

    st.markdown('<div class="side-label">A note on answers</div>', unsafe_allow_html=True)
    st.caption(
        "Recipe facts and statistics come from your local dataset. "
        "Ingredient checks are not a guarantee of allergy safety."
    )

st.markdown(
    """
    <div class="hero">
        <span class="eyebrow">✨ A little inspiration for your next meal</span>
        <h1>What sounds good today?</h1>
        <p>Search your recipe collection, find something to make with what you have,
        or ask Chef to help adapt a dish. Answers stay grounded in your Recipe Box.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    cards = st.columns(3)
    welcome_cards = [
        ("🔍", "Find your next favorite", "Search by dish, ingredients, or the way you want to eat."),
        ("🥕", "Make the most of your pantry", "Tell Chef what you have and get ranked recipe matches."),
        ("✨", "Make a thoughtful swap", "Explore substitutions with evidence from related recipes."),
    ]
    for column, (icon, title, copy) in zip(cards, welcome_cards):
        with column:
            st.markdown(
                f"""
                <div class="welcome-card">
                    <div class="welcome-icon">{icon}</div>
                    <div class="welcome-title">{title}</div>
                    <div class="welcome-copy">{copy}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar="🧑‍🍳" if message["role"] == "assistant" else "🙂"):
        render_message(message["content"])

prompt = st.chat_input("Ask Chef about recipes, ingredients, or substitutions…")
if prompt:
    st.session_state.pending_prompt = prompt

prompt = st.session_state.pending_prompt
if prompt:
    st.session_state.pending_prompt = None
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🙂"):
        render_message(prompt)

    with st.chat_message("assistant", avatar="🧑‍🍳"):
        with st.spinner("Checking your Recipe Box…"):
            try:
                answer = bot.reply(prompt)
            except Exception as exc:
                answer = f"I couldn't complete that request: {exc}"
                st.error(answer)
            else:
                render_message(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})

st.session_state.recipe_session = bot.s
bot.con.close()

st.markdown(
    '<div class="footnote">Made for good food and better answers · Always check labels for allergy safety</div>',
    unsafe_allow_html=True,
)

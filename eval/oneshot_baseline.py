"""Shows where a plain one-shot LLM answer (no database) is ungrounded, next to what this system computes.
Needs GEMINI_API_KEY and a built DB:   python eval/oneshot_baseline.py --db data/recipes.db"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from recipebot import llm
from recipebot.chat import Bot

ap = argparse.ArgumentParser(); ap.add_argument("--db", default="data/recipes.db"); a = ap.parse_args()
if not llm.available():
    sys.exit("Set GEMINI_API_KEY (Google AI Studio) to run the one-shot baseline.")
bot = Bot(a.db, use_llm=False)
QS = ["How many recipes in the Recipe Box dataset contain both garlic and onion, and what percentage of the dataset is that?",
      "What is the median number of ingredient lines per recipe in the Recipe Box dataset?",
      "How many calories are in the Recipe Box banana bread recipe?"]
for q in QS:
    print("=" * 100, "\nQ:", q, "\n\n--- one-shot LLM (no data access) ---\n", llm.generate(q) or "(no answer)")
    print("\n--- this system ---\n", bot.reply(q.replace("in the Recipe Box dataset", "").replace("the Recipe Box ", "")))

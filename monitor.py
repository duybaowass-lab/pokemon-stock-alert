import os
import re
import json
import time
import hashlib
import requests
from datetime import datetime, timezone
from urllib.parse import quote_plus

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "").strip()

ZIP_CODE = "91732"
STATE_FILE = "stock_state.json"

# Lower number = faster, less timeout/block.
# You can change to 15 later if it works well.
MAX_PAGES_PER_RUN = 10

# Set to False later if you don't want "bot checked" message every run.
SEND_HEARTBEAT = True

LOCAL_HINTS = [
    "91732",
    "el monte",
    "rosemead",
    "montebello",
    "pasadena",
    "west covina",
    "city of industry",
    "baldwin park",
    "covina",
    "glendora",
    "chino",
    "monrovia",
    "arcadia",
    "azusa",
    "whittier",
    "alhambra",
    "temple city",
    "san gabriel",
]

STOCK_TERMS = [
    "add to cart",
    "in stock",
    "available",
    "available now",
    "ready today",
    "ship it",
    "shipping",
    "delivery",
    "pickup",
    "pick up",
    "available for pickup",
    "free pickup",
    "same day delivery",
]

ONLINE_TERMS = [
    "ship it",
    "shipping",
    "delivery",
    "add to cart",
    "online",
]

INSTORE_TERMS = [
    "pickup",
    "pick up",
    "available for pickup",
    "ready today",
    "store pickup",
    "in-store",
    "in store",
]

OUT_OF_STOCK_TERMS = [
    "out of stock",
    "sold out",
    "currently unavailable",
    "not available",
    "unavailable",
    "no longer available",
    "coming soon",
]

BLOCK_TERMS = [
    "access denied",
    "captcha",
    "verify you are human",
    "robot",
    "robots",
    "blocked",
    "no robots allowed",
]

# Search terms for many Pokémon products
SEARCH_TERMS = [
    "pokemon trading cards",
    "pokemon tcg",
    "pokemon cards",
    "pokemon elite trainer box",
    "pokemon booster bundle",
    "pokemon booster box",
    "pokemon collection box",
    "pokemon premium collection",
    "pokemon ultra premium collection",
    "pokemon super premium collection",
    "pokemon tin",
    "pokemon mini tin",
    "pokemon blister",
    "pokemon 3 pack blister",
    "pokemon sleeved booster",
    "pokemon build and battle",
    "pokemon binder collection",
    "pokemon poster collection",
    "pokemon tech sticker collection",
    "pokemon surprise box",
    "pokemon prismatic evolutions",
    "prismatic evolutions elite trainer box",
    "prismatic evolutions booster bundle",
    "prismatic evolutions tech sticker collection",
    "prismatic evolutions super premium collection",
    "pokemon ascended heroes",
    "ascended heroes elite trainer box",
    "ascended heroes booster bundle",
    "pokemon chaos rising",
    "chaos rising elite trainer box",
    "chaos rising booster bundle",
    "mega evolution chaos rising",
    "pokemon 151",
    "pokemon scarlet violet 151",
    "pokemon surging sparks",
    "pokemon journey together",
    "pokemon destined rivals",
    "pokemon twilight masquerade",
    "pokemon paldea evolved",
    "pokemon obsidian flames",
    "pokemon crown zenith",
    "pokemon shrouded fable",
]

STORES = {
    "Best Buy": lambda q: f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(q)}&loc={ZIP_CODE}",
    "Target": lambda q: f"https://www.target.com/s?searchTerm={quote_plus(q)}",
    "Walmart": lambda q: f"https://www.walmart.com/search?q={quote_plus(q)}",
    "Costco": lambda q: f"https://www.costco.com/CatalogSearch?keyword={quote_plus(q)}",
    "Sam's Club": lambda q: f"https://www.samsclub.com/s/{quote_plus(q)}",
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def make_key(item):
    raw = f"{item['store']}|{item['name']}|{item['url']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_text(html):
    text = html.lower()
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def find_hits(text, terms):
    return [term for term in terms if term in text]


def send_discord(content):
    if not WEBHOOK:
        print("Missing DISCORD_WEBHOOK secret.")
        return False

    try:
        r = requests.post(WEBHOOK, json={"content": content}, timeout=30)
        print("Discord status:", r.status_code)
        print("Discord response:", r.text[:200])
        return 200 <= r.status_code < 300
    except Exception as e:
        print("Discord error:", e)
        return False


def build_items():
    items = []

    # Important: interleave stores.
    # This avoids checking only Best Buy first and timing out many times.
    for term in SEARCH_TERMS:
        for store, builder in STORES.items():
            items.append({
                "store": store,
                "name": term,
                "url": builder(term),
            })

    return items


def choose_items(state):
    all_items = build_items()
    cursor = int(state.get("_cursor", 0))

    selected = []
    for i in range(MAX_PAGES_PER_RUN):
        index = (cursor + i) % len(all_items)
        selected.append(all_items[index])

    state["_cursor"] = (cursor + MAX_PAGES_PER_RUN) % len(all_items)
    return selected


def check_item(item):
    print(f"\nChecking {item['store']} - {item['name']}")
    print(item["url"])

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    try:
        r = requests.get(item["url"], headers=headers, timeout=20)
        print("HTTP status:", r.status_code)

        text = clean_text(r.text)

        block_hits = find_hits(text, BLOCK_TERMS)
        if r.status_code in [403, 429] or block_hits:
            return {
                "status": "blocked",
                "confidence": "low",
                "mode": "unknown",
                "reason": "Store blocked or challenged request.",
                "signals": block_hits,
            }

        if "pokemon" not in text and "pokémon" not in text:
            return {
                "status": "unknown",
                "confidence": "low",
                "mode": "unknown",
                "reason": "No clear Pokemon content found.",
                "signals": [],
            }

        stock_hits = find_hits(text, STOCK_TERMS)
        online_hits = find_hits(text, ONLINE_TERMS)
        instore_hits = find_hits(text, INSTORE_TERMS)
        local_hits = find_hits(text, LOCAL_HINTS)
        oos_hits = find_hits(text, OUT_OF_STOCK_TERMS)

        score = 0
        score += len(stock_hits) * 2
        score += len(online_hits)
        score += len(instore_hits) * 2
        score += len(local_hits) * 2
        score -= len(oos_hits) * 3

        modes = []

        if online_hits:
            modes.append("online")

        if instore_hits or local_hits:
            modes.append(f"in-store near {ZIP_CODE}")

        mode = " + ".join(modes) if modes else "unknown"

        signals = list(dict.fromkeys(
            stock_hits + online_hits + instore_hits + local_hits + oos_hits
        ))

        if score >= 6 and stock_hits and not oos_hits:
            return {
                "status": "likely_stock",
                "confidence": "high",
                "mode": mode,
                "reason": "Strong stock signals found.",
                "signals": signals,
            }

        if score >= 3 and stock_hits:
            return {
                "status": "possible_stock",
                "confidence": "medium",
                "mode": mode,
                "reason": "Possible stock signals found.",
                "signals": signals,
            }

        if oos_hits:
            return {
                "status": "out_of_stock",
                "confidence": "medium",
                "mode": "unknown",
                "reason": "Out-of-stock signals found.",
                "signals": signals,
            }

        return {
            "status": "unknown",
            "confidence": "low",
            "mode": "unknown",
            "reason": "No strong stock signal.",
            "signals": signals,
        }

    except Exception as e:
        return {
            "status": "error",
            "confidence": "low",
            "mode": "unknown",
            "reason": str(e),
            "signals": [],
        }


def should_alert(old_status, new_status):
    stock_statuses = ["likely_stock", "possible_stock"]

    if new_status not in stock_statuses:
        return False

    # First run creates baseline. No spam.
    if old_status is None:
        return False

    if old_status != new_status:
        return True

    return False


def main():
    state = load_state()
    mention = f"<@{DISCORD_USER_ID}>" if DISCORD_USER_ID else ""
    now = datetime.now(timezone.utc).isoformat()

    items = choose_items(state)

    print(f"Checking {len(items)} pages near ZIP {ZIP_CODE}")

    checked_count = 0
    error_count = 0
    blocked_count = 0
    possible_count = 0
    likely_count = 0

    for item in items:
        key = make_key(item)
        old_status = state.get(key, {}).get("status")

        result = check_item(item)
        new_status = result["status"]

        checked_count += 1

        if new_status == "error":
            error_count += 1
        elif new_status == "blocked":
            blocked_count += 1
        elif new_status == "possible_stock":
            possible_count += 1
        elif new_status == "likely_stock":
            likely_count += 1

        print("Old:", old_status)
        print("New:", new_status)
        print("Confidence:", result["confidence"])
        print("Mode:", result["mode"])
        print("Reason:", result["reason"])
        print("Signals:", result["signals"])

        if should_alert(old_status, new_status):
            emoji = "🚨" if result["confidence"] == "high" else "⚠️"

            message = (
                f"{mention} {emoji} **Pokémon Restock Alert**\n"
                f"**Store:** {item['store']}\n"
                f"**Search:** {item['name']}\n"
                f"**ZIP:** {ZIP_CODE}\n"
                f"**Type:** {result['mode']}\n"
                f"**Confidence:** {result['confidence']}\n"
                f"**Status:** {new_status}\n"
                f"**Signals:** {', '.join(result['signals'][:8]) if result['signals'] else 'None'}\n"
                f"**Link:** {item['url']}"
            )

            send_discord(message)
        else:
            print("No Discord alert sent.")

        state[key] = {
            "store": item["store"],
            "name": item["name"],
            "url": item["url"],
            "status": new_status,
            "confidence": result["confidence"],
            "mode": result["mode"],
            "reason": result["reason"],
            "signals": result["signals"],
            "last_checked": now,
        }

        time.sleep(2)

    save_state(state)

    if SEND_HEARTBEAT:
        heartbeat = (
            f"✅ **Pokemon bot checked stores near ZIP {ZIP_CODE}**\n"
            f"Pages checked: {checked_count}\n"
            f"Likely stock: {likely_count}\n"
            f"Possible stock: {possible_count}\n"
            f"Blocked: {blocked_count}\n"
            f"Errors/timeouts: {error_count}\n"
            f"Time: {now}"
        )
        send_discord(heartbeat)


if __name__ == "__main__":
    main()

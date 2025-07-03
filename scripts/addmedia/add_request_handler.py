import asyncio
from discord_notify import send_discord_message
from .search_imdb import search_imdb
from .radarr_sonarr_check import is_already_in_radarr, is_already_in_plex

# from radarr_sonarr_api import add_to_service  # Disabled for testing


# Ask for user confirmation via Discord
async def ask_user_confirmation(media_info, media_type, channel):
    confirm_message = await channel.send(
        f"🔍 **{media_type.capitalize()} found**: {media_info['title']} ({media_info['year']})\n"
        f"Poster: {media_info['poster']}\n"
        f"✅ Reply with `yes` to confirm or `no` to cancel."
    )

    def check(m):
        return m.channel == channel and m.content.lower() in ["yes", "no"]

    try:
        msg = await channel.bot.wait_for("message", timeout=30.0, check=check)
        return msg.content.lower() == "yes"
    except asyncio.TimeoutError:
        await channel.send("⏱️ Timeout. Request cancelled.")
        return False


# Main function called by the bot
async def handle_add_request(media_type, media_title, channel, bot):
    await channel.send(f"⏳ Searching for: `{media_title}`...")

    results = search_imdb(media_title, media_type)
    if not results or len(results) == 0:
        await channel.send("❌ No results found.")
        return False

    results = results[:8]
    msg = "**Results found:**\n"
    for i, media in enumerate(results, start=1):
        msg += f"{i}. {media['title']} ({media['year']})\n"
    msg += "9. Rewrite the title\n10. Cancel"
    await channel.send(msg)

    def check_choice(m):
        return (
            m.channel == channel
            and m.content.isdigit()
            and int(m.content) in range(1, 11)
        )

    try:
        response = await bot.wait_for("message", timeout=30.0, check=check_choice)
        choice = int(response.content)
    except asyncio.TimeoutError:
        await channel.send("⏱️ Timeout. Request cancelled.")
        return False

    if choice == 9:
        await channel.send("✍️ Please rewrite the movie/show title.")
        return False
    elif choice == 10:
        await channel.send("❌ Request cancelled.")
        return False

    selected = results[choice - 1]

    # Show detailed information
    ratings = selected.get("ratings", [])
    rating_text = (
        ", ".join([f"{r['Source']}: {r['Value']}" for r in ratings])
        if ratings
        else "None"
    )
    plot = selected.get("plot", "No summary available.")

    await channel.send(
        f"🎬 **{selected['title']} ({selected['year']})**\n"
        f"📝 Plot: {plot}\n"
        f"⭐ Ratings: {rating_text}\n"
        f"🖼️ Poster: {selected['poster']}\n"
        f"✅ Reply with `yes` to confirm, `no` to cancel."
    )

    def check_confirm(m):
        return m.channel == channel and m.content.lower() in ["yes", "no"]

    try:
        confirmation = await bot.wait_for("message", timeout=30.0, check=check_confirm)
        if confirmation.content.lower() != "yes":
            await channel.send("❌ Request cancelled.")
            return False
    except asyncio.TimeoutError:
        await channel.send("⏱️ Timeout. Request cancelled.")
        return False

    # Check if already in Radarr
    imdb_id = selected.get("imdb_id")
    await channel.send(f"🔍 Checking Radarr for IMDb ID: `{imdb_id}`...")
    if await is_already_in_radarr(imdb_id):
        await channel.send(
            "📀 This movie is already in the Radarr library. No action taken."
        )
        return False
    else:
        await channel.send("✅ Not found in Radarr.")

    # Check Plex availability
    await channel.send(f"🔍 Checking Plex for title: `{selected['title']}`...")
    if await is_already_in_plex(selected["title"]):
        await channel.send(
            "🎞️ This movie is already available in Plex. No action taken."
        )
        return False
    else:
        await channel.send("✅ Not found in Plex.")

    # Proceed to add (simulate or real)
    # add_to_service(media_type, selected)
    await channel.send(
        f"✅ Test passed. Next step: add downloading for **{selected['title']} ({selected['year']})**."
    )
    return True

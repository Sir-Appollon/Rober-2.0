# add_request_handler.py
import asyncio
from discord_notify import send_discord_message
from search_imdb import search_imdb

# from radarr_sonarr_api import add_to_service  # Désactivé pour simulation


# Demande de confirmation simple via Discord
async def ask_user_confirmation(media_info, channel):
    # Message initial
    confirm_message = await channel.send(
        f"🔍 **{media_info['type'].capitalize()} trouvé** : {media_info['title']} ({media_info['year']})\n"
        f"Avec cette affiche : {media_info['poster']}\n"
        f"✅ Réponds avec `oui` pour confirmer ou `non` pour annuler."
    )

    def check(m):
        return m.channel == channel and m.content.lower() in ["oui", "non"]

    try:
        msg = await channel.bot.wait_for("message", timeout=30.0, check=check)
        return msg.content.lower() == "oui"
    except asyncio.TimeoutError:
        await channel.send("⏱️ Temps écoulé. Requête annulée.")
        return False

# Fonction principale appelée par le bot
async def handle_add_request(media_type, media_title, channel, bot):
    await channel.send(f"⏳ Recherche de : `{media_title}`...")

    results = search_imdb(media_title, media_type)
    if not results or len(results) == 0:
        await channel.send("❌ Aucun résultat trouvé.")
        return False

    results = results[:8]
    msg = "**Résultats trouvés :**\n"
    for i, media in enumerate(results, start=1):
        msg += f"{i}. {media['title']} ({media['year']})\n"
    msg += "9. Réécrire le titre\n10. Annuler"
    await channel.send(msg)

    def check_choice(m):
        return m.channel == channel and m.content.isdigit() and int(m.content) in range(1, 11)

    try:
        response = await bot.wait_for("message", timeout=30.0, check=check_choice)
        choice = int(response.content)
    except asyncio.TimeoutError:
        await channel.send("⏱️ Temps écoulé. Requête annulée.")
        return False

    if choice == 9:
        await channel.send("✍️ Réécris le nom du film.")
        return False
    elif choice == 10:
        await channel.send("❌ Requête annulée.")
        return False

    selected = results[choice - 1]

    # Présenter détails
    ratings = selected.get('ratings', [])
    rating_text = ', '.join([f"{r['Source']}: {r['Value']}" for r in ratings]) if ratings else "Aucune"
    plot = selected.get('plot', 'Aucun résumé disponible.')

    await channel.send(
        f"🎬 **{selected['title']} ({selected['year']})**\n"
        f"📝 Résumé : {plot}\n"
        f"⭐ Notes : {rating_text}\n"
        f"🖼️ Affiche : {selected['poster']}\n"
        f"✅ Tape `oui` pour confirmer, `non` pour annuler."
    )

    def check_confirm(m):
        return m.channel == channel and m.content.lower() in ["oui", "non"]

    try:
        confirmation = await bot.wait_for("message", timeout=30.0, check=check_confirm)
        if confirmation.content.lower() != "oui":
            await channel.send("❌ Requête annulée.")
            return False
    except asyncio.TimeoutError:
        await channel.send("⏱️ Temps écoulé. Requête annulée.")
        return False

    # Simulation d’ajout
    # add_to_service(media_type, selected)
    await channel.send(f"📥 Téléchargement lancé pour **{selected['title']} ({selected['year']})**.")
    return True



# Demande de confirmation simple via Discord
async def ask_user_confirmation(media_info, media_type, channel):
    confirm_message = await channel.send(
        f"🔍 **{media_type.capitalize()} trouvé** : {media_info['title']} ({media_info['year']})\n"
        f"Avec cette affiche : {media_info['poster']}\n"
        f"✅ Réponds avec `oui` pour confirmer ou `non` pour annuler."
    )

    def check(m):
        return m.channel == channel and m.content.lower() in ["oui", "non"]

    try:
        msg = await channel.bot.wait_for('message', timeout=30.0, check=check)
        return msg.content.lower() == "oui"
    except asyncio.TimeoutError:
        await channel.send("⏱️ Temps écoulé. Requête annulée.")
        return False

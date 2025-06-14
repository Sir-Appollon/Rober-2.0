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
async def handle_add_request(media_type, media_title, channel):
    await channel.send(
        f"[DEBUG] Début traitement de la requête : {media_type} - {media_title}"
    )
    print(f"[DEBUG] Recherche IMDb pour : {media_title}")
    media_info = search_imdb(media_title, media_type)
    print(f"[DEBUG] Résultat IMDb : {media_info}")

    await channel.send(
        f"🔍 **{media_type.capitalize()} trouvé** : {media_info['title']} ({media_info['year']})\n"
        f"Avec cette affiche : {media_info['poster']}\n"
        f"✅ Réponds avec `oui` pour confirmer ou `non` pour annuler."
    )

    confirmed = await ask_user_confirmation(media_info, media_type, channel)
    print(f"[DEBUG] Confirmation utilisateur : {confirmed}")
    await channel.send(f"[DEBUG] Réponse utilisateur : {confirmed}")

    if confirmed:
        await channel.send(
            f"✅ Données envoyées à **{media_type.capitalize()}** pour téléchargement !"
        )
        # add_to_service(media_type, media_info)  # Désactivé
        return True
    else:
        await channel.send("❌ Requête annulée.")
        return False


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

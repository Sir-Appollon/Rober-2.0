import requests
import os
from dotenv import load_dotenv

from search_imdb import search_imdb
from radarr_sonarr_api import add_to_service

async def handle_add_request(ctx, title, content_type):
    await ctx.send(f"🧠 Bon… je cherche le numéro du film **`{title}`** dans IMDb ou OMDb, ou je sais plus trop où… 🤓")

    result = search_imdb(title, content_type)

    if not result:
        await ctx.send("😞 J’ai rien trouvé. Peut-être une faute dans le titre ? Ou alors c’est un film inventé ! 🎬💨")
        return

    await ctx.send("📡 Accès à la base de données réussi ! Voilà ce que j’ai trouvé 👇")

    # Formater les notes si disponibles
    ratings_text = ""
    if "ratings" in result:
        for r in result["ratings"]:
            ratings_text += f"⭐ {r['Source']}: {r['Value']}\n"

    confirm_message = await ctx.send(
        f"🎬 **{result['title']}** ({result['year']})\n"
        f"🔗 IMDb ID : `{result['imdb_id']}`\n"
        f"{ratings_text}\n"
        "Tu veux que je l’ajoute ? ✅ pour oui, ❌ pour non."
    )

    await confirm_message.add_reaction("✅")
    await confirm_message.add_reaction("❌")

    def check(reaction, user):
        return (
            user == ctx.author and
            reaction.message.id == confirm_message.id and
            str(reaction.emoji) in ["✅", "❌"]
        )

    try:
        reaction, _ = await ctx.bot.wait_for("reaction_add", timeout=30.0, check=check)

        if str(reaction.emoji) == "✅":
            await ctx.send("📦 Ok, je tente d’ajouter ça… 🎯")
            success = add_to_service(result, content_type)

            if success:
                await ctx.send("✅ C’est bon ! Le film est dans la file de téléchargement 🎉")
            else:
                await ctx.send("⚠️ Hmm... j’ai eu un problème en parlant à Radarr ou Sonarr. Tu peux réessayer ou râler gentiment 🤖")
        else:
            await ctx.send("🛑 Ok, j’annule. T’avais qu’à être sûr dès le début 😅")
    except:
        await ctx.send("⏰ Temps écoulé ! Tu réfléchissais trop. Je passe à autre chose. 😴")

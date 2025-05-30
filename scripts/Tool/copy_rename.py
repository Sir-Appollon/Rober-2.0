import os
import shutil

# Dossiers source et destination
source_dir = "/mnt/media/tv/Death's Game/Season 1"
dest_dir = "/mnt/media/extra/downloads/complete/Deaths.Game.S01.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK"

# Liste des nouveaux noms de fichiers (tu les vois ici clairement)
new_files = {
    "S01E01": "Deaths.Game.S01E01.Death.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E02": "Deaths.Game.S01E02.The.Reason.Youre.Going.to.Hell.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E03": "Deaths.Game.S01E03.Death.Cant.Take.Anything.Away.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E04": "Deaths.Game.S01E04.The.Reason.Youre.Afraid.of.Death.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E05": "Deaths.Game.S01E05.It.Is.Impossible.to.Break.Free.and.Fight.against.Death.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E06": "Deaths.Game.S01E06.Memory.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E07": "Deaths.Game.S01E07.Opportunity.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv",
    "S01E08": "Deaths.Game.S01E08.Dont.Go.Looking.For.Death.Death.Will.Come.Find.You.1080p.AMZN.WEB-DL.DDP2.0.H.264-MARK.mkv"
}

# Création du dossier de destination si nécessaire
os.makedirs(dest_dir, exist_ok=True)

# Traitement des fichiers dans le dossier source
for filename in os.listdir(source_dir):
    if not filename.endswith(".mkv"):
        continue
    for ep_code, new_name in new_files.items():
        if ep_code in filename:
            src_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(dest_dir, new_name)
            shutil.copy2(src_path, dest_path)
            print(f"[COPIED] {filename} → {new_name}")
            break

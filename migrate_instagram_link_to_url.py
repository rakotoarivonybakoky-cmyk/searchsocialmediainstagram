import sys
import time
from config import load_config
from pymongo import MongoClient, UpdateOne
from pymongo.errors import AutoReconnect

def run_migration(dry_run=True, test_one=False):
    cfg = load_config()
    client = MongoClient(cfg.mongodb_uri)
    col = client[cfg.mongodb_db_name][cfg.mongodb_collection_name]

    query = {
        "$or": [
            {"socialAccounts.instagram.URL": {"$exists": True}},
            {"socialAccounts.instagram.link": {"$exists": True}}
        ]
    }

    if test_one:
        doc = col.find_one(query)
        if not doc:
            print("Aucun document trouvé avec socialAccounts.instagram.URL ou link")
            return

        orig_ig = doc.get("socialAccounts", {}).get("instagram", [])
        print(f"--- TEST SUR 1 DOCUMENT ({doc['_id']}) ---")
        print("AVANT :", orig_ig)

        new_ig = []
        for item in orig_ig:
            if isinstance(item, dict):
                new_item = {}
                # url en minuscule en premier
                raw_url = item.get("url") or item.get("URL") or item.get("link")
                if raw_url:
                    new_item["url"] = raw_url

                for k, v in item.items():
                    if k not in ("url", "URL", "link"):
                        new_item[k] = v
                new_ig.append(new_item)
            else:
                new_ig.append(item)

        print("APRÈS (avec 'url' minuscule) :", new_ig)

        if not dry_run:
            res = col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"socialAccounts.instagram": new_ig}}
            )
            print(f"Modifié avec succès : {res.modified_count} doc.")
            fresh = col.find_one({"_id": doc["_id"]})
            print("VÉRIFICATION EN BASE :", fresh.get("socialAccounts", {}).get("instagram"))
        return

    print(f"--- DÉMARRAGE DE LA MIGRATION VERS 'url' MINUSCULE (dry_run={dry_run}) ---")

    while True:
        # Traitement par lots pour supporter de légères déconnexions réseau
        cursor = col.find(query, {"_id": 1, "socialAccounts.instagram": 1}, no_cursor_timeout=True).limit(5000)
        docs = list(cursor)
        cursor.close()

        if not docs:
            print("Aucun document restant à migrer.")
            break

        batch = []
        total_modified = 0
        for doc in docs:
            orig_ig = doc.get("socialAccounts", {}).get("instagram", [])
            new_ig = []
            has_change = False
            for item in orig_ig:
                if isinstance(item, dict) and ("URL" in item or "link" in item):
                    has_change = True
                    raw_url = item.get("url") or item.get("URL") or item.get("link")
                    new_item = {"url": raw_url}
                    for k, v in item.items():
                        if k not in ("url", "URL", "link"):
                            new_item[k] = v
                    new_ig.append(new_item)
                else:
                    new_ig.append(item)

            if has_change:
                batch.append(
                    UpdateOne(
                        {"_id": doc["_id"]},
                        {"$set": {"socialAccounts.instagram": new_ig}}
                    )
                )

        if batch:
            if not dry_run:
                retries = 3
                while retries > 0:
                    try:
                        b_res = col.bulk_write(batch, ordered=False)
                        print(f"Lot validé : {b_res.modified_count} documents mis à jour vers 'url'.", flush=True)
                        break
                    except AutoReconnect as e:
                        retries -= 1
                        print(f"AutoReconnect, attente 2s... ({retries} essais restants)")
                        time.sleep(2)
            else:
                print(f"[DRY-RUN] Lot simulé : {len(batch)} documents.")

    print("MIGRATION TERMINÉE !")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    if mode == "--test-one":
        run_migration(dry_run=False, test_one=True)
    elif mode == "--apply":
        run_migration(dry_run=False, test_one=False)
    else:
        run_migration(dry_run=True, test_one=False)

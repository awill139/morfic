import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
from morfic.catalog import load_catalog

def main():
    jelly=next(x for x in load_catalog() if x.id=="jellyfin")
    assert jelly.deployment_plan is not None
    assert jelly.deployment_plan.container_image=="jellyfin/jellyfin:latest"
    assert jelly.deployment_plan.port==8096
    assert jelly.deployment_plan.media_mounts is True
    print("CATALOG RECIPE PASS: Jellyfin bypasses LLM planning")

if __name__=="__main__": main()

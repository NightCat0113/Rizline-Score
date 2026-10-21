import UnityPy
from pathlib import Path

path = Path("download/bundles/14938d88efc2cdcacc685538999b40aa.bundle")
env = UnityPy.load(str(path))
bundle = env.files[next(iter(env.files))]
for name, item in bundle.files.items():
    if str(name).endswith(".resS"):
        env.register_cab(str(name), item)
by_id = {obj.path_id: obj for obj in env.objects}


def sprite_name(pid: int) -> str:
    obj = by_id.get(pid)
    if obj is None:
        return "missing"
    try:
        data = obj.read()
    except Exception as exc:
        return type(exc).__name__
    image = getattr(data, "image", None)
    size = None if image is None else image.size
    return f"{getattr(data, 'm_Name', '')} {size}"


default = None
for obj in by_id.values():
    if obj.type.name != "MonoBehaviour":
        continue
    try:
        tree = obj.read_typetree()
    except Exception:
        continue
    if tree.get("m_Name") == "Default":
        default = tree
        break


def walk(transform_id: int, parent: str = "") -> None:
    transform = by_id.get(transform_id)
    if transform is None:
        return
    tree = transform.read_typetree()
    game = by_id.get((tree.get("m_GameObject") or {}).get("m_PathID"))
    name = ""
    if game is not None:
        game_tree = game.read_typetree()
        name = str(game_tree.get("m_Name") or "")
        if name in {"Image", "TextImage"}:
            for component in game_tree.get("m_Component") or []:
                behaviour = by_id.get((component.get("component") or {}).get("m_PathID"))
                if behaviour is None or behaviour.type.name != "MonoBehaviour":
                    continue
                component_tree = behaviour.read_typetree()
                files = component_tree.get("spriteFiles")
                sprite = (component_tree.get("m_Sprite") or {}).get("m_PathID")
                if not files and not sprite:
                    continue
                print(f" NODE {parent}/{name}")
                if sprite:
                    print("  default", sprite_name(sprite))
                for entry in files or []:
                    image_id = (entry.get("image") or {}).get("m_PathID")
                    print(
                        "  lang",
                        entry.get("language"),
                        "rollback",
                        entry.get("isRollbackImage"),
                        sprite_name(image_id),
                    )
    for child in tree.get("m_Children") or []:
        child_id = (child or {}).get("m_PathID")
        if child_id:
            walk(int(child_id), name)


for config in default.get("seriesConfigs") or []:
    index = config.get("seriesIndex")
    if index not in {11, 13, 14, 15, 16, 17, 18}:
        continue
    poster_id = (config.get("poster") or {}).get("m_PathID")
    print("SERIES", index, by_id[poster_id].read_typetree().get("m_Name"))
    game = by_id[poster_id].read_typetree()
    for component in game.get("m_Component") or []:
        candidate = by_id.get((component.get("component") or {}).get("m_PathID"))
        if candidate is not None and candidate.type.name in {"Transform", "RectTransform"}:
            walk((component.get("component") or {}).get("m_PathID"))
            break

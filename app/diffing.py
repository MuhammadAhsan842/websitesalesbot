"""Version diff for replacement documents. Humans resolve; the worker does not pick a clause."""


def clause_diff(previous: dict | None, current: dict | None) -> list[dict]:
    previous = previous or {}
    current = current or {}
    keys = sorted(set(previous) | set(current))
    changes = []
    for key in keys:
        if key.startswith("_"):
            continue
        old, new = previous.get(key), current.get(key)
        if old == new:
            continue
        changes.append({"field": key, "from": old, "to": new})
    return changes

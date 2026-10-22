"""Group by real landmark identity, preserving identically named regions."""

from .models import Region


REGION_ROLES = {"dialog", "alertdialog", "form", "main", "navigation", "region", "complementary", "search"}


def group_regions(elements, previous=None):
    landmarks = {e.identity: e for e in elements if e.role in REGION_ROLES}
    groups = {"page": Region("page", "Page controls")}
    old = {e.identity: e.signature() for e in previous.elements} if previous else {}
    changed = {}
    for element in elements:
        ancestors = [landmarks[key] for key in element.region_path if key in landmarks]
        dialogs = [e for e in ancestors if e.role in ("dialog", "alertdialog")]
        owner = dialogs[-1] if dialogs else (ancestors[-1] if ancestors else None)
        if element.identity in landmarks and not dialogs:
            owner = element
        key = owner.identity if owner else "page"
        if key not in groups:
            groups[key] = Region(key, f'{owner.role} {owner.name or "(unnamed)"}', ref=owner.ref)
        group = groups[key]
        element.region = key
        group.elements.append(element)
        if owner and owner.role in ("dialog", "alertdialog"):
            group.priority = max(group.priority, 100)
        if element.states.get("focused"):
            group.priority += 1000
        if previous and old.get(element.identity) != element.signature():
            changed[key] = changed.get(key, 0) + 1
    for key, group in groups.items():
        group.priority += min(changed.get(key, 0), 10)
    return sorted((g for g in groups.values() if g.elements), key=lambda g: -g.priority)

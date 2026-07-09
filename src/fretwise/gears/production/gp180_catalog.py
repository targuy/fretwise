import re

SECTION_RE = re.compile(r"- \*\*🟢\s*(?P<module>.*?)\s+—")

CATALOG_MODULES = {
    "NR",
    "PRE",
    "WAH",
    "DST",
    "N→S",
    "AMP",
    "CAB / IR",
    "EQ",
    "MOD",
    "DLY",
    "RVB",
}


def build_gp180_allowed_catalog(markdown_text):
    items = {module: [] for module in CATALOG_MODULES}
    current_module = None
    table_header = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        section = SECTION_RE.search(line)
        if section:
            current_module = _clean_module(section.group("module"))
            table_header = []
            continue
        if current_module not in CATALOG_MODULES:
            continue
        if not line.startswith("|"):
            table_header = []
            continue
        cells = _table_cells(line)
        if not cells:
            continue
        if _is_header(cells):
            table_header = cells
            continue
        if _is_separator(cells):
            continue
        if not _is_model_table(current_module, table_header):
            continue
        if current_module == "N→S":
            if cells[0].isdigit() and len(cells) > 1:
                detail = " · ".join(cell for cell in cells[2:] if cell and cell != "—")
                value = f"{cells[0]} {cells[1]}"
                if detail:
                    value = f"{value} ({detail})"
                items[current_module].append(value)
        else:
            items[current_module].append(cells[0])

    for module in CATALOG_MODULES:
        items[module] = _unique(items[module])
    if not items["NR"]:
        items["NR"] = ["Gate 1", "Gate 2", "Gate 3"]
    items["CAB / IR"].extend(_missing_cab_names(items["CAB / IR"]))
    items["VOL"] = ["Volume", "Level", "Boost solo", "EXP volume"]
    return _format_catalog(items)


def _clean_module(module):
    module = module.strip()
    if module.startswith("N"):
        return "N→S"
    if module.startswith("CAB"):
        return "CAB / IR"
    return module.split()[0] if module.split()[0] in CATALOG_MODULES else module


def _table_cells(line):
    return [cell.strip().strip("*") for cell in line.strip("|").split("|")]


def _is_header(cells):
    first = cells[0].lower()
    return first in {"modèle", "bloc", "#", "usage", "contexte", "test", "paramètre", "position"}


def _is_separator(cells):
    first = cells[0].lower()
    return not first or set(first.replace(" ", "")) <= {"-"}


def _is_model_table(module, header):
    if not header:
        return False
    first = header[0].lower()
    if module == "N→S":
        return first == "#" and len(header) > 1 and header[1].lower() == "nom"
    return first == "modèle"


def _unique(values):
    seen = set()
    result = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _missing_cab_names(existing):
    names = []
    for name in ["AC", "OM", "JUMBO", "Bird", "GA"]:
        if name not in existing:
            names.append(name)
    for index in range(1, 21):
        names.append(f"User IR {index}")
    return names


def _format_catalog(items):
    sections = [
        "# GP-180 ALLOWED MODEL CATALOG (STRICT)",
        "",
        "Use these exact names for `gp180.blocks[].model`. "
        "For an inactive or bypassed block, use `None`.",
        "If the ideal gear is absent, choose the closest listed GP-180 model, "
        "set `matchQuality`, and document `gap`.",
        "",
    ]
    order = ["NR", "PRE", "WAH", "DST", "N→S", "AMP", "CAB / IR", "EQ", "MOD", "DLY", "RVB", "VOL"]
    for module in order:
        values = ["None", *items.get(module, [])]
        sections.append(f"## {module}")
        sections.append("; ".join(values))
        sections.append("")
    return "\n".join(sections).strip()

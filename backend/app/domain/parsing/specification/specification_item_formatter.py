import re


class SpecificationPartsFormatter:
    STEEL_GRADE_EN_RE = re.compile(r"EN\s*\d+(?:\.\d+)+", re.IGNORECASE)
    GOST_EN_RE = re.compile(r"EN\s*\d+(?:-\d+)+", re.IGNORECASE)
    # «по EN DN 114,3» — обозначение номинального диаметра по EN, не отдельный стандарт (ГОСТ пустой).
    _EN_DN_NOMINAL_HEAD = re.compile(r"^EN\s+DN\b", re.IGNORECASE)

    @staticmethod
    def _normalize_en_code(code: str) -> str:
        m = re.search(r"EN\s*(.+)", code or "", re.IGNORECASE)
        if not m:
            return (code or "").strip().upper()
        return f"EN {m.group(1).strip()}".upper()

    @staticmethod
    def _is_en_dn_nominal_tail(tail: str) -> bool:
        return bool(SpecificationPartsFormatter._EN_DN_NOMINAL_HEAD.match((tail or "").strip()))

    @staticmethod
    def format(name: str, item):
        name = " ".join(name.replace("\n", " ").split())

        material_match = re.search(
            r"материал:\s*(.+?)(?=,|$)", name, re.IGNORECASE
        )

        if material_match:
            material_str = material_match.group(1).strip()
            parts = material_str.split(" = ")
            # Новый надёжный шаблон:
            # - steel_grade: EN 1.4404, EN 1.4541 (через точку)
            # - gost: EN 1092-1, EN 10217-7 (через дефис)
            steel_grade_match = SpecificationPartsFormatter.STEEL_GRADE_EN_RE.search(material_str)
            gost_match = SpecificationPartsFormatter.GOST_EN_RE.search(material_str)
            if steel_grade_match is None:
                steel_grade_match = SpecificationPartsFormatter.STEEL_GRADE_EN_RE.search(name)
            if gost_match is None:
                gost_match = SpecificationPartsFormatter.GOST_EN_RE.search(name)

            if len(parts) == 2:
                steel_grade_fallback = parts[0].strip()
                second_part = parts[1].strip()
                gost_after_po = re.search(
                    r"по\s*(EN\s*\d+(?:-\d+)+)",
                    second_part,
                    re.IGNORECASE,
                )
                if gost_after_po:
                    gost_match = re.search(
                        SpecificationPartsFormatter.GOST_EN_RE.pattern,
                        gost_after_po.group(1),
                        re.IGNORECASE,
                    )

                if " по " in second_part:
                    material, gost_tail = second_part.split(" по ", 1)
                    gost_tail = gost_tail.strip()
                    if SpecificationPartsFormatter._is_en_dn_nominal_tail(gost_tail):
                        gost = ""
                    else:
                        gost = " ".join(gost_tail.split()[0:2])
                else:
                    material = second_part
                    gost = ""

                item.material = material
                item.steel_grade = (
                    SpecificationPartsFormatter._normalize_en_code(steel_grade_match.group(0))
                    if steel_grade_match
                    else steel_grade_fallback
                )
                raw_gost = (
                    SpecificationPartsFormatter._normalize_en_code(gost_match.group(0))
                    if gost_match
                    else gost
                )
                if SpecificationPartsFormatter._is_en_dn_nominal_tail(raw_gost):
                    item.gost = ""
                else:
                    item.gost = raw_gost
            else:
                if steel_grade_match:
                    item.steel_grade = SpecificationPartsFormatter._normalize_en_code(
                        steel_grade_match.group(0)
                    )
                if gost_match:
                    item.gost = SpecificationPartsFormatter._normalize_en_code(gost_match.group(0))

        item.dimensions = SpecificationPartsFormatter._extract_dimensions(name)

    @staticmethod
    def _extract_dimensions(name: str) -> str:
        # Ищем два размера с дефисом (оба с запятыми)
        match = re.search(
            r"(\d+),(\d+)[хx](\d+),(\d+)\s*-\s*(\d+),(\d+)[хx](\d+),(\d+)", name
        )
        if match:
            nums = match.groups()
            s1 = f"Ø{nums[0]},{nums[1]}x{nums[2]},{nums[3]}"
            s2 = f"Ø{nums[4]},{nums[5]}x{nums[6]},{nums[7]}"
            return f"{s1} - {s2}"

        # Ищем один размер с двумя запятыми: 114,3х3,2
        match = re.search(r"(\d+),(\d+)[хx](\d+),(\d+)", name)
        if match:
            nums = match.groups()
            return f"Ø{nums[0]},{nums[1]}x{nums[2]},{nums[3]}"

        # Ищем размер с запятой в диаметре и целой толщиной: 76,1х2
        match = re.search(r"(\d+),(\d+)[хx](\d+)", name)
        if match:
            nums = match.groups()
            return f"Ø{nums[0]},{nums[1]}x{nums[2]}"

        # Ищем размер с целыми числами: 273х4
        match = re.search(r"(\d+)[хx](\d+)", name)
        if match:
            nums = match.groups()
            return f"Ø{nums[0]}x{nums[1]}"

        # Ищем формат с DN и двумя запятыми: DN48,3x3,2
        match = re.search(r"DN(\d+),(\d+)[хx](\d+),(\d+)", name)
        if match:
            nums = match.groups()
            return f"Ø{nums[0]},{nums[1]}x{nums[2]},{nums[3]}"

        # Ищем два размера с DN и пробелами: DN48 3х3 2 - 60 3х3 2
        match = re.search(
            r"DN(\d+)\s+(\d+)[хx](\d+)\s+(\d+)\s*-\s*(\d+)\s+(\d+)[хx](\d+)\s+(\d+)",
            name,
        )
        if match:
            nums = match.groups()
            s1 = f"Ø{nums[0]},{nums[1]}x{nums[2]},{nums[3]}"
            s2 = f"Ø{nums[4]},{nums[5]}x{nums[6]},{nums[7]}"
            return f"{s1} - {s2}"

        # Ищем один размер с DN и пробелами: DN48 3х3 2
        match = re.search(r"DN(\d+)\s+(\d+)[хx](\d+)\s+(\d+)", name)
        if match:
            nums = match.groups()
            return f"Ø{nums[0]},{nums[1]}x{nums[2]},{nums[3]}"

        # Ищем только DN: DN50, DN 50, DN114,3, DN 114,3
        match = re.search(r"DN\s*(\d+(?:,\d+)?)", name, re.IGNORECASE)
        if match:
            return f"Ø{match.group(1)}"

        # Если ничего не нашли
        return ""


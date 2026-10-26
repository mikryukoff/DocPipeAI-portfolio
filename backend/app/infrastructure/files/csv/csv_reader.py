class CSVReader:
    def read(self, path: str) -> list[list[str]]:
        rows: list[list[str]] = []

        with open(path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip().replace('"', "")
                if not raw:
                    continue
                rows.append([c.strip() for c in raw.split(",") if c.strip()])

        return rows
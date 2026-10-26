import mimetypes
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from backend.app.api.crop_path_utils import resolve_safe_crop_file
from backend.app.application.exceptions import PipelineNotFoundError, ValidationError
from backend.app.domain.parsing.drawing_4_store import (
    Drawing4Entry,
    Drawing4Store,
    get_drawing_4_store,
)
from backend.app.domain.parsing.drawing_tag_normalize import (
    instrument_tag_dedup_key,
    normalize_instrument_tag_label,
)
from backend.app.infrastructure.repositories.embedment_draft_repository import (
    EmbedmentDraftRepository,
)
from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository
from backend.app.infrastructure.repositories.spec_item_repository import (
    SpecItemRepository,
    _MAX_EMBEDMENT_ELEMENT_ROWS,
    _normalize_embedment_element_row,
)

class InstrumentEmbedmentService:
    @staticmethod
    def _api_project_root() -> Path:
        return Path(__file__).resolve().parents[4]

    @staticmethod
    def _normalize_text(value: object) -> str:
        return str(value or "").strip() or "---"

    @staticmethod
    def _is_meaningful_name(value: object) -> bool:
        name = str(value or "").strip()
        return bool(name and name != "---")

    @classmethod
    def _build_elements_output(cls, item_name: str, extra: dict) -> list[dict]:
        elements_out: list[dict] = []
        raw_els = extra.get("embedment_elements")
        if isinstance(raw_els, list) and raw_els:
            for element in raw_els:
                if not isinstance(element, dict):
                    continue
                elements_out.append(
                    {
                        "name": cls._normalize_text(element.get("name")),
                        "location": cls._normalize_text(element.get("location")),
                        "dn": cls._normalize_text(element.get("dn")),
                        "pn": cls._normalize_text(element.get("pn")),
                        "material_grade": cls._normalize_text(element.get("material_grade")),
                        "gost": cls._normalize_text(element.get("gost")),
                    }
                )
        if not elements_out:
            elements_out.append(
                {
                    "name": cls._normalize_text(item_name),
                    "location": cls._normalize_text(extra.get("location")),
                    "dn": cls._normalize_text(extra.get("dn")),
                    "pn": cls._normalize_text(extra.get("pn")),
                    "material_grade": cls._normalize_text(extra.get("material_grade")),
                    "gost": cls._normalize_text(extra.get("gost")),
                }
            )
        return elements_out

    def _embedment_group_from_item(self, item: SpecItemORM) -> dict:
        extra = dict(item.extra or {})
        group_key = (extra.get("embedment_group_key") or "").strip()
        instrument_tag = (extra.get("instrument_tag") or "").strip()
        rel_path = (extra.get("drawing_image_path") or "").strip()
        crop_url = ""
        if rel_path:
            crop_url = f"/pipelines/embedment-crop-image?path={quote(rel_path, safe='')}"
        elements_out = self._build_elements_output(item.name, extra)
        return {
            "embedment_group_key": group_key,
            "instrument_tag": instrument_tag,
            "drawing_image_path": rel_path,
            "crop_image_url": crop_url,
            "name": item.name,
            "page": item.page,
            "position": item.position,
            "location": extra.get("location", "---") or "---",
            "dn": extra.get("dn", "---") or "---",
            "pn": extra.get("pn", "---") or "---",
            "material_grade": extra.get("material_grade", "---") or "---",
            "gost": extra.get("gost", "---") or "---",
            "elements": elements_out,
        }

    @staticmethod
    def _normalize_tag_for_lookup(raw: str) -> str:
        """NFKC, дефисы, ZWSP, пробелы — для цепочки resolve (без смены регистра)."""
        return normalize_instrument_tag_label(raw)

    @staticmethod
    def _admin_tag_dedup_key(tag: str) -> str:
        """Ключ схлопывания: NFKC, дефисы, пробелы, регистр."""
        return instrument_tag_dedup_key(tag)

    @classmethod
    def _resolve_tag_lookup_candidates(cls, raw: str) -> list[str]:
        """Цепочка строк для Drawing4Store.resolve (регистр и нормализация)."""
        s = str(raw or "").strip()
        if not s:
            return []
        norm = cls._normalize_tag_for_lookup(s)
        out: list[str] = []
        for x in (s, norm):
            if x and x not in out:
                out.append(x)
        if norm:
            for x in (norm.casefold(), norm.lower(), norm.upper()):
                if x and x not in out:
                    out.append(x)
        return out

    @staticmethod
    def _spec_item_sort_key(item: SpecItemORM) -> tuple[str, int, int]:
        page = str(item.page or "")
        pos = item.position
        try:
            pos_n = int(pos) if pos is not None else 0
        except (TypeError, ValueError):
            pos_n = 0
        iid = int(getattr(item, "id", 0) or 0)
        return (page, pos_n, iid)

    @staticmethod
    def _prefer_spec_item(current: SpecItemORM | None, candidate: SpecItemORM) -> SpecItemORM:
        if current is None:
            return candidate
        kc = InstrumentEmbedmentService._spec_item_sort_key(current)
        kn = InstrumentEmbedmentService._spec_item_sort_key(candidate)
        return candidate if kn < kc else current

    @staticmethod
    def _unique_peer_tags_for_admin(peer_tags: frozenset[str] | set[str]) -> list[str]:
        """Один пункт списка на номер: убирает повторы, отличающиеся только регистром/пробелами."""
        seen_cf: set[str] = set()
        out: list[str] = []
        for raw in sorted(peer_tags):
            t = (raw or "").strip()
            if not t:
                continue
            cf = InstrumentEmbedmentService._admin_tag_dedup_key(t)
            if cf in seen_cf:
                continue
            seen_cf.add(cf)
            out.append(t)
        return out

    def _try_resolve_embedment_entry(self, store: Drawing4Store, value: str):
        for cand in self._resolve_tag_lookup_candidates(value):
            entry = store.resolve(cand)
            if entry is not None:
                return entry
        return None

    def _drawing_entry_for_embedment_item(
        self,
        item: SpecItemORM,
        store: Drawing4Store,
    ):
        extra = dict(item.extra or {})
        tag = (extra.get("instrument_tag") or "").strip()
        gk = (extra.get("embedment_group_key") or "").strip()
        entry = self._try_resolve_embedment_entry(store, tag) if tag else None
        if entry is None and gk:
            entry = self._try_resolve_embedment_entry(store, gk)
        return entry

    @staticmethod
    def _drawing_cluster_peer_key(entry) -> frozenset[str] | None:
        peer_cf = frozenset(
            InstrumentEmbedmentService._admin_tag_dedup_key(str(t))
            for t in entry.peer_tags
            if str(t).strip()
        )
        return peer_cf if peer_cf else None

    @staticmethod
    def _admin_flat_row_score(row: dict) -> tuple[int, int, int]:
        g = row.get("group") or {}
        peers = g.get("peer_tags")
        peer_n = len(peers) if isinstance(peers, list) else 0
        crop = 1 if str(g.get("crop_image_url") or "").strip() else 0
        path = 1 if str(g.get("drawing_image_path") or "").strip() else 0
        return (peer_n, crop, path)

    def _build_merged_draw_groups_for_pipeline(
        self,
        items: list[SpecItemORM],
        store: Drawing4Store,
    ) -> list[tuple[SpecItemORM, list[str]]]:
        """Объединяет Drawing4Entry с пересекающимися peer_tags (разные ключи JSON — одна группа)."""
        pairs: list[tuple[SpecItemORM, Drawing4Entry]] = []
        entry_objs: list[Drawing4Entry] = []
        entry_ids: dict[int, int] = {}

        for item in items:
            entry = self._drawing_entry_for_embedment_item(item, store)
            if entry is None:
                continue
            peer_cf = self._drawing_cluster_peer_key(entry)
            if peer_cf is None:
                continue
            eid = id(entry)
            if eid not in entry_ids:
                entry_ids[eid] = len(entry_objs)
                entry_objs.append(entry)
            pairs.append((item, entry))

        n = len(entry_objs)
        if n == 0:
            return []

        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[pi] = pj

        def norm_set(idx: int) -> frozenset[str]:
            ent = entry_objs[idx]
            return frozenset(
                self._admin_tag_dedup_key(str(t))
                for t in ent.peer_tags
                if str(t).strip()
            )

        for i in range(n):
            for j in range(i + 1, n):
                if norm_set(i) & norm_set(j):
                    union(i, j)

        roots: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            roots[find(i)].append(i)

        root_items: dict[int, list[SpecItemORM]] = defaultdict(list)
        for item, entry in pairs:
            idx = entry_ids[id(entry)]
            root_items[find(idx)].append(item)

        out: list[tuple[SpecItemORM, list[str]]] = []
        for root, ent_indices in roots.items():
            raw_peers: set[str] = set()
            for ei in ent_indices:
                for t in entry_objs[ei].peer_tags:
                    ts = str(t).strip()
                    if ts:
                        raw_peers.add(ts)
            peer_list = self._unique_peer_tags_for_admin(frozenset(raw_peers))
            if not peer_list:
                continue
            rep: SpecItemORM | None = None
            for it in root_items[root]:
                rep = self._prefer_spec_item(rep, it)
            if rep is not None:
                out.append((rep, peer_list))

        out.sort(key=lambda tp: self._spec_item_sort_key(tp[0]))
        return out

    def _admin_flat_entries_from_peer_list(
        self,
        *,
        pipeline_name: str,
        item: SpecItemORM,
        peer_list: list[str],
    ) -> list[dict]:
        base = self._embedment_group_from_item(item)
        rows: list[dict] = []
        for display_tag in peer_list:
            g = dict(base)
            g["instrument_tag"] = display_tag
            g["peer_tags"] = peer_list
            rows.append(
                {
                    "pipeline_name": pipeline_name,
                    "page": item.page,
                    "position": item.position,
                    "list_instrument_tag": display_tag,
                    "group": g,
                }
            )
        return rows

    def _admin_flat_entries_for_item(
        self,
        *,
        pipeline_name: str,
        item: SpecItemORM,
        store: Drawing4Store,
    ) -> list[dict]:
        """По одной строке списка на каждый номер прибора: канонический и alias из drawing_4 JSON."""
        base = self._embedment_group_from_item(item)
        extra = dict(item.extra or {})
        tag = (extra.get("instrument_tag") or "").strip()
        gk = (extra.get("embedment_group_key") or "").strip()
        entry = self._drawing_entry_for_embedment_item(item, store)

        if entry is not None:
            peer_list = self._unique_peer_tags_for_admin(entry.peer_tags)
            out: list[dict] = []
            for display_tag in peer_list:
                g = dict(base)
                g["instrument_tag"] = display_tag
                g["peer_tags"] = peer_list
                out.append(
                    {
                        "pipeline_name": pipeline_name,
                        "page": item.page,
                        "position": item.position,
                        "list_instrument_tag": display_tag,
                        "group": g,
                    }
                )
            return out

        display = (tag or gk).strip()
        g = dict(base)
        if display:
            g["instrument_tag"] = display
        return [
            {
                "pipeline_name": pipeline_name,
                "page": item.page,
                "position": item.position,
                "list_instrument_tag": display,
                "group": g,
            }
        ]

    async def list_pipeline_embedments(
        self,
        *,
        pipeline_name: str,
        repo: PipelineRepository,
        spec_repo: SpecItemRepository,
    ) -> dict:
        pipeline_id = await repo.get_id_by_name(pipeline_name)
        if pipeline_id is None:
            raise PipelineNotFoundError(pipeline_name)

        items = await spec_repo.list_instrument_embedments(pipeline_id)
        seen: set[str] = set()
        groups: list[dict] = []
        for item in items:
            extra = dict(item.extra or {})
            group_key = (extra.get("embedment_group_key") or "").strip()
            instrument_tag = (extra.get("instrument_tag") or "").strip()
            dedup_key = group_key if group_key else (instrument_tag if instrument_tag else f"id:{item.id}")
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            groups.append(self._embedment_group_from_item(item))
        return {"pipeline_name": pipeline_name, "groups": groups}

    async def list_all_embedments_flat_for_admin(
        self,
        *,
        repo: PipelineRepository,
        spec_repo: SpecItemRepository,
        drawing_store: Drawing4Store | None = None,
    ) -> dict:
        """Закладные: merge чертежей по peer_tags; один пункт на тег в админке, в т.ч. при нескольких трубопроводах."""
        store = drawing_store if drawing_store is not None else get_drawing_4_store()
        names = await repo.list_names()
        embedments: list[dict] = []
        for pipeline_name in sorted(names):
            pipeline_id = await repo.get_id_by_name(pipeline_name)
            if pipeline_id is None:
                continue
            items = await spec_repo.list_instrument_embedments(pipeline_id)
            tag_only_rep: dict[tuple[str, str], SpecItemORM] = {}
            bare_items: list[SpecItemORM] = []
            pn = pipeline_name.strip()

            merged_draw = self._build_merged_draw_groups_for_pipeline(items, store)
            covered_by_draw: set[str] = set()
            for _, peer_list in merged_draw:
                for t in peer_list:
                    cf = self._admin_tag_dedup_key(str(t))
                    if cf:
                        covered_by_draw.add(cf)

            for rep_item, peer_list in merged_draw:
                embedments.extend(
                    self._admin_flat_entries_from_peer_list(
                        pipeline_name=pipeline_name,
                        item=rep_item,
                        peer_list=peer_list,
                    )
                )

            for item in items:
                entry = self._drawing_entry_for_embedment_item(item, store)
                if entry is not None and self._drawing_cluster_peer_key(entry) is not None:
                    continue
                extra = dict(item.extra or {})
                tag = (extra.get("instrument_tag") or "").strip()
                gk = (extra.get("embedment_group_key") or "").strip()
                display = tag or gk
                dk = self._admin_tag_dedup_key(display)
                if dk and dk in covered_by_draw:
                    continue
                if dk:
                    ck = (pn, dk)
                    tag_only_rep[ck] = self._prefer_spec_item(tag_only_rep.get(ck), item)
                else:
                    bare_items.append(item)

            for item in tag_only_rep.values():
                embedments.extend(
                    self._admin_flat_entries_for_item(
                        pipeline_name=pipeline_name,
                        item=item,
                        store=store,
                    )
                )
            for item in bare_items:
                embedments.extend(
                    self._admin_flat_entries_for_item(
                        pipeline_name=pipeline_name,
                        item=item,
                        store=store,
                    )
                )

        def _sort_key(entry: dict) -> tuple[int, str, str, str]:
            pos = entry.get("position")
            try:
                pos_n = int(pos) if pos is not None else 0
            except (TypeError, ValueError):
                pos_n = 0
            pipe = str(entry.get("pipeline_name") or "")
            page = str(entry.get("page") or "")
            tag = str(entry.get("list_instrument_tag") or "")
            return (pos_n, pipe, page, tag)

        embedments.sort(key=_sort_key)

        def _norm_position_for_dedup(pos) -> int | str:
            try:
                return int(pos)
            except (TypeError, ValueError):
                return str(pos or "")

        def _dedup_identity(entry: dict) -> tuple:
            pipe = str(entry.get("pipeline_name") or "").strip().casefold()
            tag_raw = str(entry.get("list_instrument_tag") or "")
            tag_cf = self._admin_tag_dedup_key(tag_raw)
            if tag_cf:
                # Один тег — одна карточка в настройках, даже если закладная в нескольких трубопроводах
                return ("instrument", tag_cf)
            pos = entry.get("position")
            page = str(entry.get("page") or "")
            return ("bare", pipe, _norm_position_for_dedup(pos), page)

        buckets: dict[tuple, list[dict]] = defaultdict(list)
        for e in embedments:
            buckets[_dedup_identity(e)].append(e)

        unique: list[dict] = []
        for ident, rows in buckets.items():
            best = max(rows, key=self._admin_flat_row_score)
            if ident[0] == "instrument":
                names = sorted(
                    {str(r.get("pipeline_name") or "").strip() for r in rows if str(r.get("pipeline_name") or "").strip()},
                    key=str.casefold,
                )
                merged = dict(best)
                merged["pipeline_names"] = names
                unique.append(merged)
            else:
                unique.append(best)

        def _sort_key_admin(entry: dict) -> tuple[str, str, int, str, str]:
            tag = str(entry.get("list_instrument_tag") or "")
            tag_cf = self._admin_tag_dedup_key(tag)
            pnames = entry.get("pipeline_names")
            if isinstance(pnames, list) and pnames:
                pipe_sort = ",".join(sorted((str(p) for p in pnames if str(p).strip()), key=str.casefold))
            else:
                pipe_sort = str(entry.get("pipeline_name") or "")
            pos = entry.get("position")
            try:
                pos_n = int(pos) if pos is not None else 0
            except (TypeError, ValueError):
                pos_n = 0
            page = str(entry.get("page") or "")
            return (tag_cf, pipe_sort.casefold(), pos_n, page, tag)

        unique.sort(key=_sort_key_admin)

        return {"embedments": unique}

    async def patch_pipeline_embedments(
        self,
        *,
        pipeline_name: str,
        body,
        repo: PipelineRepository,
        spec_repo: SpecItemRepository,
        drawing_store: Drawing4Store,
    ) -> dict:
        pipeline_id = await repo.get_id_by_name(pipeline_name)
        if pipeline_id is None:
            raise PipelineNotFoundError(pipeline_name)

        group_key_in = (body.embedment_group_key or "").strip()
        instrument_tag_in = (body.instrument_tag or "").strip()

        entry = drawing_store.resolve(instrument_tag_in) if instrument_tag_in else None
        if entry is None and group_key_in:
            entry = drawing_store.resolve(group_key_in)

        if entry is not None:
            use_key = entry.group_key
            peers = {str(p).strip() for p in entry.peer_tags if str(p).strip()}
            items_preview = await spec_repo.list_instrument_embedments(pipeline_id)
            merged_draw = self._build_merged_draw_groups_for_pipeline(items_preview, drawing_store)
            seed_cf = self._admin_tag_dedup_key(instrument_tag_in) if instrument_tag_in else ""
            if not seed_cf and group_key_in:
                seed_cf = self._admin_tag_dedup_key(group_key_in)
            if seed_cf and merged_draw:
                for _rep, peer_list in merged_draw:
                    if any(self._admin_tag_dedup_key(str(x)) == seed_cf for x in peer_list):
                        peers = {str(x).strip() for x in peer_list if str(x).strip()}
                        break
        else:
            use_key = group_key_in or instrument_tag_in
            peers = set()
            if instrument_tag_in:
                peers.add(instrument_tag_in)
            if group_key_in:
                peers.add(group_key_in)

        elements_payload: list[dict] | None = None
        if body.elements is not None:
            elements_payload = [element.model_dump() for element in body.elements[:20]]

        if elements_payload is not None:
            norm_rows = [
                _normalize_embedment_element_row(e)
                for e in elements_payload[:_MAX_EMBEDMENT_ELEMENT_ROWS]
                if isinstance(e, dict)
            ]
            if any(not self._is_meaningful_name(row.get("name")) for row in norm_rows):
                raise ValidationError(
                    "Наименование обязательно для каждой строки закладной",
                    details={"reason": "embedment_name_required"},
                )
            if not norm_rows:
                norm_rows = [
                    _normalize_embedment_element_row(
                        {
                            "name": "---",
                            "location": body.location,
                            "dn": body.dn,
                            "pn": body.pn,
                            "material_grade": body.material_grade,
                            "gost": body.gost,
                        }
                    )
                ]
        else:
            norm_rows = [
                _normalize_embedment_element_row(
                    {
                        "name": "---",
                        "location": body.location,
                        "dn": body.dn,
                        "pn": body.pn,
                        "material_grade": body.material_grade,
                        "gost": body.gost,
                    }
                )
            ]
        draft_payload = {"embedment_elements": norm_rows}

        drawing_path = (entry.path if entry else "").strip()
        dedup = EmbedmentDraftRepository.compute_dedup_key(drawing_path, use_key)

        updated = await spec_repo.update_instrument_embedment_group(
            pipeline_id=pipeline_id,
            embedment_group_key=use_key,
            peer_tags=peers,
            location=body.location,
            dn=body.dn,
            pn=body.pn,
            material_grade=body.material_grade,
            gost=body.gost,
            elements=elements_payload,
            drawing_image_path=drawing_path or None,
        )

        await EmbedmentDraftRepository(spec_repo.session).upsert(
            pipeline_id=pipeline_id,
            dedup_key=dedup,
            embedment_group_key=use_key,
            drawing_image_path=drawing_path,
            peer_tags=sorted(peers),
            payload=draft_payload,
        )
        return {"updated": updated}

    def resolve_embedment_crop_image(
        self,
        *,
        relative_path: str,
        crop_output_dir: str,
    ) -> tuple[Path, str]:
        root = self._api_project_root()
        crop_root = (root / Path(crop_output_dir)).resolve()
        found = resolve_safe_crop_file(
            relative_path,
            project_root=root,
            allowed_crop_root=crop_root,
        )
        if found is None:
            raise ValidationError("Некорректный или отсутствующий путь к изображению")
        media_type, _ = mimetypes.guess_type(found.name)
        return found, media_type or "application/octet-stream"

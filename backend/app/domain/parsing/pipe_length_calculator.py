from backend.app.domain.models.pipeline import PipelineLength
from backend.app.domain.models.specification import Specification


class PipeLengthCalculator:
    def __init__(self):
        # Временное хранилище для накопления данных
        # Структура: {pipeline_name: {dimensions: PipelineLength}}
        self._accumulated_data: dict[str, dict[str, PipelineLength]] = {}
    
    def accumulate(self, pipeline_name: str, spec: Specification) -> None:
        """Накопление данных для конкретного трубопровода"""
        
        if pipeline_name not in self._accumulated_data:
            self._accumulated_data[pipeline_name] = {}
        
        pipeline_lengths = self._accumulated_data[pipeline_name]
        
        for pipe in spec.pipes:
            if not pipe.dimensions or pipe.quantity <= 0:
                continue

            dimensions = pipe.dimensions
            if dimensions not in pipeline_lengths:
                pipeline_lengths[dimensions] = PipelineLength(
                    total_length=0.0, 
                    pages=[]
                )

            entry = pipeline_lengths[dimensions]
            entry.total_length += float(pipe.quantity)

            if spec.page and spec.page not in entry.pages:
                entry.pages.append(spec.page)
    
    def finalize(self, pipeline_name: str) -> dict[str, PipelineLength]:
        """Финализация расчетов для конкретного трубопровода"""
        if pipeline_name in self._accumulated_data:
            # Копируем рассчитанные длины в объект pipeline
            pipelines_len = {}
            
            for dim, length_data in self._accumulated_data[pipeline_name].items():
                # Сортируем страницы
                sorted_pages = sorted(length_data.pages, key=self._page_key)
                pipelines_len[dim] = PipelineLength(
                    total_length=round(length_data.total_length, 1),
                    pages=sorted_pages
                )

            return pipelines_len
        return {}

    @staticmethod
    def _page_key(page: str):
        return tuple(int(p) for p in page.split("."))

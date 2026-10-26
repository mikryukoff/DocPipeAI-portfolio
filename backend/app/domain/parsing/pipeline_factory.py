from backend.app.domain.models.pipeline import Pipeline, FlowDirection, PipelineParameters
from backend.app.shared.pipeline_number_format import normalize_pipeline_name


class PipelineFactory:
    def create(self, name: str) -> Pipeline:
        return Pipeline(
            name=normalize_pipeline_name(name),
            medium="",
            mounting_scheme="",
            flow_direction=FlowDirection("", ""),
            parameters=PipelineParameters(
                gost_category="",
                working_pressure="",
                working_temperature="",
                calculated_pressure="",
                calculated_temperature="",
                strength_test_pressure="",
                strength_test_method="",
                strength_test_type="",
                strength_test_duration="",
                strength_test_result="",
                material="",
                installation_date="",
                welding_type="",
                welding_material=""
            ),
            specifications=[],
            pipelines_len={},
        )

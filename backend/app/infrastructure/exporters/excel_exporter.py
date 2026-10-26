import json
import pandas as pd
from loguru import logger

def json_to_excel(json_file_path, excel_file_path):
    # Загружаем JSON файл
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Открываем объект записи Excel
    with pd.ExcelWriter(excel_file_path, engine='openpyxl') as writer:
        
        # Лист 1: Параметры линии трубопровода (без спецификации)
        pipeline_params = []
        
        for pipeline_id, pipeline_data in data.items():
            # Собираем все страницы (листы) для этого трубопровода
            all_pages = []
            for spec in pipeline_data.get('specifications', []):
                page = spec.get('page', '')
                if page and page not in all_pages:
                    all_pages.append(page)
            
            param_row = {
                'ID трубопровода': pipeline_id,
                'Среда': pipeline_data.get('medium', ''),
                'Схема монтажа': pipeline_data.get('mounting_scheme', ''),
                'Начало потока': pipeline_data.get('flow_direction', {}).get('start', ''),
                'Конец потока': pipeline_data.get('flow_direction', {}).get('end', ''),
                'Категория ГОСТ': pipeline_data.get('parameters', {}).get('gost_category', ''),
                'Рабочее давление': pipeline_data.get('parameters', {}).get('working_pressure', ''),
                'Рабочая температура': pipeline_data.get('parameters', {}).get('working_temperature', ''),
                'Расчетное давление': pipeline_data.get('parameters', {}).get('calculated_pressure', ''),
                'Расчетная температура': pipeline_data.get('parameters', {}).get('calculated_temperature', ''),
                'Давление испытания': pipeline_data.get('parameters', {}).get('strength_test_pressure', ''),
                'Метод испытания': pipeline_data.get('parameters', {}).get('strength_test_method', ''),
                'Материал': pipeline_data.get('parameters', {}).get('material', ''),
                'Листы': ', '.join(all_pages)  # Все листы этого трубопровода
            }
            pipeline_params.append(param_row)
        
        # Формируем таблицу с параметрами трубопроводов
        if pipeline_params:
            df_params = pd.DataFrame(pipeline_params)
            df_params.to_excel(writer, sheet_name='Параметры трубопроводов', index=False)
        
        # Лист 2: Спецификации
        specs_data = []
        
        for pipeline_id, pipeline_data in data.items():
            for spec in pipeline_data.get('specifications', []):
                page = spec.get('page', '')
                
                # Обрабатываем арматуру
                for item in spec.get('pipeline_armature', []):
                    spec_row = {
                        'ID трубопровода': pipeline_id,
                        'Страница спецификации': page,
                        'Тип элемента': 'Арматура',
                        'Позиция': item.get('position'),
                        'Наименование': item.get('name'),
                        'Единица': item.get('unit'),
                        'Количество': item.get('quantity'),
                        'Материал': item.get('material', ''),
                        'Марка стали': item.get('steel_grade', ''),
                        'ГОСТ': item.get('gost', ''),
                        'Размеры': item.get('dimensions', ''),
                        'Примечание': item.get('note', ''),
                        'Листы': page  # Столбец с листами этого элемента
                    }
                    specs_data.append(spec_row)

                for item in spec.get("instrument_embedments", []):
                    spec_row = {
                        "ID трубопровода": pipeline_id,
                        "Страница спецификации": page,
                        "Тип элемента": "Закладная",
                        "Позиция": item.get("position"),
                        "Наименование": item.get("name"),
                        "Единица": item.get("unit"),
                        "Количество": item.get("quantity"),
                        "Материал": item.get("material", ""),
                        "Марка стали": item.get("material_grade", ""),
                        "ГОСТ": item.get("gost", ""),
                        "Размеры": "",
                        "Примечание": item.get("instrument_tag", ""),
                        "Листы": page,
                    }
                    specs_data.append(spec_row)
                
                # Обрабатываем трубы
                for item in spec.get('pipes', []):
                    spec_row = {
                        'ID трубопровода': pipeline_id,
                        'Страница спецификации': page,
                        'Тип элемента': 'Труба',
                        'Позиция': item.get('position'),
                        'Наименование': item.get('name'),
                        'Единица': item.get('unit'),
                        'Количество': item.get('quantity'),
                        'Материал': item.get('material', ''),
                        'Марка стали': item.get('steel_grade', ''),
                        'ГОСТ': item.get('gost', ''),
                        'Размеры': item.get('dimensions', ''),
                        'Примечание': '',
                        'Листы': page  # Столбец с листами этого элемента
                    }
                    specs_data.append(spec_row)
                
                # Обрабатываем соединительные части
                for item in spec.get('connection_parts', []):
                    spec_row = {
                        'ID трубопровода': pipeline_id,
                        'Страница спецификации': page,
                        'Тип элемента': 'Соединительная часть',
                        'Позиция': item.get('position'),
                        'Наименование': item.get('name'),
                        'Единица': item.get('unit'),
                        'Количество': item.get('quantity'),
                        'Материал': item.get('material', ''),
                        'Марка стали': item.get('steel_grade', ''),
                        'ГОСТ': item.get('gost', ''),
                        'Размеры': item.get('dimensions', ''),
                        'Примечание': '',
                        'Листы': page  # Столбец с листами этого элемента
                    }
                    specs_data.append(spec_row)
                
                # Обрабатываем фланцы
                for item in spec.get('flanges', []):
                    spec_row = {
                        'ID трубопровода': pipeline_id,
                        'Страница спецификации': page,
                        'Тип элемента': 'Фланец',
                        'Позиция': item.get('position'),
                        'Наименование': item.get('name'),
                        'Единица': item.get('unit'),
                        'Количество': item.get('quantity'),
                        'Материал': '',
                        'Марка стали': '',
                        'ГОСТ': '',
                        'Размеры': '',
                        'Примечание': '',
                        'Листы': page  # Столбец с листами этого элемента
                    }
                    specs_data.append(spec_row)
                
                # Обрабатываем опоры
                for item in spec.get('supports', []):
                    spec_row = {
                        'ID трубопровода': pipeline_id,
                        'Страница спецификации': page,
                        'Тип элемента': 'Опора',
                        'Позиция': item.get('position'),
                        'Наименование': item.get('name'),
                        'Единица': item.get('unit'),
                        'Количество': item.get('quantity'),
                        'Материал': '',
                        'Марка стали': '',
                        'ГОСТ': '',
                        'Размеры': '',
                        'Примечание': '',
                        'Листы': page  # Столбец с листами этого элемента
                    }
                    specs_data.append(spec_row)
        
        # Формируем таблицу со спецификациями
        if specs_data:
            df_specs = pd.DataFrame(specs_data)
            df_specs.to_excel(writer, sheet_name='Спецификации', index=False)
        
        # Лист 3: Общая длина труб на каждой линии
        pipe_lengths_data = []
        
        for pipeline_id, pipeline_data in data.items():
            if 'pipelines_len' in pipeline_data:
                for diameter, length_info in pipeline_data['pipelines_len'].items():
                    length_row = {
                        'ID трубопровода': pipeline_id,
                        'Диаметр': diameter,
                        'Общая длина, м': length_info.get('total_length', 0),
                        'Страницы': ', '.join(length_info.get('pages', [])),
                    }
                    pipe_lengths_data.append(length_row)
        
        # Если данных о длинах нет, создаем пустой лист с заголовками
        if pipe_lengths_data:
            df_lengths = pd.DataFrame(pipe_lengths_data)
            df_lengths.to_excel(writer, sheet_name='Длины труб', index=False)
        else:
            # Формируем пустую таблицу с заголовками
            empty_lengths = pd.DataFrame(columns=[
                'ID трубопровода', 'Диаметр', 'Общая длина, м', 'Страницы'
            ])
            empty_lengths.to_excel(writer, sheet_name='Длины труб', index=False)
    
    logger.info("Excel exported. path={}", excel_file_path)
    logger.info(
        "Excel stats. params={} specs={} lengths={} pipelines={}",
        len(pipeline_params),
        len(specs_data),
        len(pipe_lengths_data),
        len(data),
    )
    
    return {
        'params_count': len(pipeline_params),
        'specs_count': len(specs_data),
        'lengths_count': len(pipe_lengths_data),
        'total_pipelines': len(data)
    }

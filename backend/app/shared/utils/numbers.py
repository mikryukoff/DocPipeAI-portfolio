import pandas as pd
import json
from loguru import logger

def calculate_result(json_file_path):
    """
    Анализирует общую статистику заполнения информации о трубопроводах из JSON файла.
    Выводит только общую статистику и информацию о проблемных трубопроводах.
    """
    
    # Загружаем JSON файл
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    total_pipelines = len(data)
    
    # Счетчики для статистики
    pipeline_stats = {
        'total': total_pipelines,
        'with_parameters': 0,
        'with_specifications': 0,
        'with_flow_direction': 0,
        'with_lengths': 0,
        'complete_pipelines': 0,
        'problematic_pipelines': 0,
        'pipelines_by_material': {},
        'pipelines_by_medium': {}
    }
    
    # Список проблемных трубопроводов
    problematic_pipelines = []
    
    # Проверяемые поля
    required_sections = ['parameters', 'specifications', 'flow_direction', 'pipelines_len']
    required_params = [
        'gost_category',
        'working_pressure',
        'working_temperature', 
        'calculated_pressure',
        'calculated_temperature',
        'strength_test_pressure',
        'strength_test_method',
        'material'
    ]
    
    # Анализ каждого трубопровода
    for pipeline_id, pipeline_data in data.items():
        pipeline_problems = []
        
        # Проверяем наличие основных разделов
        for section in required_sections:
            if section not in pipeline_data or not pipeline_data[section]:
                pipeline_problems.append(f"Отсутствует раздел '{section}'")
        
        # Проверяем параметры
        if 'parameters' in pipeline_data:
            pipeline_stats['with_parameters'] += 1
            params = pipeline_data['parameters']
            
            # Проверяем заполненность каждого параметра
            for param in required_params:
                if param not in params or not str(params.get(param, '')).strip():
                    pipeline_problems.append(f"Не заполнен параметр '{param}'")
        else:
            pipeline_problems.append("Отсутствуют параметры")
        
        # Проверяем спецификации
        if 'specifications' in pipeline_data and pipeline_data['specifications']:
            pipeline_stats['with_specifications'] += 1
            
            # Проверяем, что в спецификациях есть хотя бы одна запись
            specs = pipeline_data['specifications']
            if not specs:
                pipeline_problems.append("Пустые спецификации")
            else:
                # Проверяем первую спецификацию как пример
                first_spec = specs[0]
                has_components = False
                for comp_type in [
                    'pipeline_armature',
                    'instrument_embedments',
                    'pipes',
                    'connection_parts',
                    'flanges',
                    'supports',
                ]:
                    if comp_type in first_spec and first_spec[comp_type]:
                        has_components = True
                        break
                
                if not has_components:
                    pipeline_problems.append("Спецификации не содержат компонентов")
        else:
            pipeline_problems.append("Отсутствуют спецификации")
        
        # Проверяем направление потока
        if 'flow_direction' in pipeline_data:
            pipeline_stats['with_flow_direction'] += 1
            flow = pipeline_data['flow_direction']
            
            if 'start' not in flow or not str(flow.get('start', '')).strip():
                pipeline_problems.append("Не указано начало потока")
            
            if 'end' not in flow or not str(flow.get('end', '')).strip():
                pipeline_problems.append("Не указан конец потока")
        else:
            pipeline_problems.append("Отсутствует направление потока")
        
        # Проверяем длины труб
        if 'pipelines_len' in pipeline_data and pipeline_data['pipelines_len']:
            pipeline_stats['with_lengths'] += 1
        else:
            pipeline_problems.append("Отсутствуют длины труб")
        
        # Подсчет по материалу
        if 'parameters' in pipeline_data and 'material' in pipeline_data['parameters']:
            material = pipeline_data['parameters']['material']
            pipeline_stats['pipelines_by_material'][material] = pipeline_stats['pipelines_by_material'].get(material, 0) + 1
        
        # Подсчет по среде
        if 'medium' in pipeline_data:
            medium = pipeline_data['medium']
            pipeline_stats['pipelines_by_medium'][medium] = pipeline_stats['pipelines_by_medium'].get(medium, 0) + 1
        
        # Определяем, полный ли трубопровод
        is_complete = (
            'parameters' in pipeline_data and 
            'specifications' in pipeline_data and pipeline_data['specifications'] and
            'flow_direction' in pipeline_data and 
            'pipelines_len' in pipeline_data and pipeline_data['pipelines_len']
        )
        
        if is_complete:
            # Проверяем все необходимые параметры
            if 'parameters' in pipeline_data:
                params = pipeline_data['parameters']
                all_params_filled = all(
                    param in params and str(params.get(param, '')).strip() 
                    for param in required_params
                )
                
                # Проверяем направление потока
                flow_complete = (
                    'flow_direction' in pipeline_data and
                    'start' in pipeline_data['flow_direction'] and 
                    str(pipeline_data['flow_direction'].get('start', '')).strip() and
                    'end' in pipeline_data['flow_direction'] and 
                    str(pipeline_data['flow_direction'].get('end', '')).strip()
                )
                
                if all_params_filled and flow_complete:
                    pipeline_stats['complete_pipelines'] += 1
                else:
                    problematic_pipelines.append({
                        'id': pipeline_id,
                        'problems': pipeline_problems
                    })
                    pipeline_stats['problematic_pipelines'] += 1
            else:
                problematic_pipelines.append({
                    'id': pipeline_id,
                    'problems': pipeline_problems
                })
                pipeline_stats['problematic_pipelines'] += 1
        else:
            problematic_pipelines.append({
                'id': pipeline_id,
                'problems': pipeline_problems
            })
            pipeline_stats['problematic_pipelines'] += 1
    
    # Выводим проблемные трубопроводы, если они есть
    if problematic_pipelines:
        
        # Группируем проблемы по типам
        problem_types = {}
        
        for pipeline in problematic_pipelines:
            for problem in pipeline['problems']:
                problem_types[problem] = problem_types.get(problem, 0) + 1
        
    # Создаем DataFrame с общей статистикой
    summary_data = [
        ['Всего трубопроводов', pipeline_stats['total']],
        ['Полностью заполненных', pipeline_stats['complete_pipelines']],
        ['С проблемами', pipeline_stats['problematic_pipelines']],
        ['Процент заполненных', f"{pipeline_stats['complete_pipelines']/pipeline_stats['total']*100:.1f}%"],
        ['Процент с проблемами', f"{pipeline_stats['problematic_pipelines']/pipeline_stats['total']*100:.1f}%"],
        ['', ''],
        ['--- Заполненность разделов ---', ''],
        ['С параметрами', f"{pipeline_stats['with_parameters']} ({pipeline_stats['with_parameters']/pipeline_stats['total']*100:.1f}%)"],
        ['Со спецификациями', f"{pipeline_stats['with_specifications']} ({pipeline_stats['with_specifications']/pipeline_stats['total']*100:.1f}%)"],
        ['С направлением потока', f"{pipeline_stats['with_flow_direction']} ({pipeline_stats['with_flow_direction']/pipeline_stats['total']*100:.1f}%)"],
        ['С длинами труб', f"{pipeline_stats['with_lengths']} ({pipeline_stats['with_lengths']/pipeline_stats['total']*100:.1f}%)"]
    ]
    
    # Добавляем статистику по материалам
    if pipeline_stats['pipelines_by_material']:
        summary_data.append(['', ''])
        summary_data.append(['--- Распределение по материалам ---', ''])
        for material, count in sorted(pipeline_stats['pipelines_by_material'].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / pipeline_stats['total']) * 100
            summary_data.append([material, f"{count} ({percentage:.1f}%)"])
    
    # Добавляем статистику по средам
    if pipeline_stats['pipelines_by_medium']:
        summary_data.append(['', ''])
        summary_data.append(['--- Распределение по средам ---', ''])
        for medium, count in sorted(pipeline_stats['pipelines_by_medium'].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / pipeline_stats['total']) * 100
            summary_data.append([medium, f"{count} ({percentage:.1f}%)"])
    
    df_summary = pd.DataFrame(summary_data, columns=['Показатель', 'Значение'])
    
    # Создаем DataFrame с проблемными трубопроводами
    problematic_data = []
    for pipeline in problematic_pipelines:
        problematic_data.append({
            'ID трубопровода': pipeline['id'],
            'Количество проблем': len(pipeline['problems']),
            'Проблемы': '; '.join(pipeline['problems'])
        })
    
    df_problematic = pd.DataFrame(problematic_data)
    
    # Сохраняем в Excel
    output_file = "data/processed/structured_files/pipeline_statistics_report.xlsx"
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_summary.to_excel(writer, sheet_name='Общая статистика', index=False)
        if not df_problematic.empty:
            df_problematic.to_excel(writer, sheet_name='Проблемные трубопроводы', index=False)
        
        # Добавляем лист с типами проблем
        if problematic_pipelines:
            problem_types_data = []
            for problem, count in sorted(problem_types.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / pipeline_stats['total']) * 100
                problem_types_data.append({
                    'Тип проблемы': problem,
                    'Количество': count,
                    'Процент': f"{percentage:.1f}%"
                })
            
            df_problem_types = pd.DataFrame(problem_types_data)
            df_problem_types.to_excel(writer, sheet_name='Типы проблем', index=False)
    
    logger.info("Pipeline statistics report saved. path={}", output_file)
    
    return {
        'total_pipelines': pipeline_stats['total'],
        'complete_pipelines': pipeline_stats['complete_pipelines'],
        'problematic_pipelines': pipeline_stats['problematic_pipelines'],
        'completion_rate': pipeline_stats['complete_pipelines']/pipeline_stats['total']*100,
        'problematic_list': problematic_pipelines,
        'report_file': output_file
    }

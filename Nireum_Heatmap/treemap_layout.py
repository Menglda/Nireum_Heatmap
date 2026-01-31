def normalize_sizes(sizes, width, height):
    """
    면적 합이 width * height가 되도록 정규화
    sizes: 값 리스트
    """
    total_size = sum(sizes)
    if total_size == 0: return []
    total_area = width * height
    return [size * total_area / total_size for size in sizes]

def worst_ratio(row, width):
    """
    현재 row의 사각형들의 가로세로비 중 가장 나쁜(1에서 먼) 값을 반환
    """
    if not row: return float('inf')
    min_area = min(row)
    max_area = max(row)
    row_area = sum(row)
    if row_area == 0 or width == 0: return float('inf')
    
    # width는 측면 길이 (현재 채우고 있는 방향의 수직 길이)
    # row_area / width = row_width (채우는 방향의 두께)
    
    return max((width ** 2 * max_area) / (row_area ** 2), (row_area ** 2) / (width ** 2 * min_area))

def layout_row(row, x, y, width, height, is_horizontal):
    """
    Row를 실제로 배치하여 좌표 리스트 반환
    is_horizontal: 가로로 자를지(True, 높이가 고정), 세로로 자를지(False, 너비가 고정)
    """
    row_area = sum(row)
    if row_area == 0: return []
    
    rects = []
    
    if is_horizontal:
        # 높이는 고정(side), 너비(row_area / height)를 채움 -> 실제로는 '세로'로 쌓이는 형태가 됨 (row_width = row_area / side)
        # Squarified 알고리즘 용어 정리:
        # layout 함수에서 width는 '컨테이너의 짧은 변'을 의미하여 전달됨.
        # 여기서는 실제 좌표계로 변환해야 함.
        
        # side가 height라고 가정
        row_width = row_area / height 
        current_y = y
        for area in row:
            h = area / row_width
            rects.append({'x': x, 'y': current_y, 'w': row_width, 'h': h})
            current_y += h
    else:
        # 너비는 고정(side), 높이(row_area / width)를 채움
        row_height = row_area / width
        current_x = x
        for area in row:
            w = area / row_height
            rects.append({'x': current_x, 'y': y, 'w': w, 'h': row_height})
            current_x += w
            
    return rects

def squarify(children, x, y, w, h):
    """
    Squarified Treemap 알고리즘 메인
    children: 정규화된 면적 리스트
    반환: [{'x':, 'y':, 'w':, 'h':}, ...]
    """
    if not children: return []
    
    # 캔버스의 짧은 변을 기준으로 함
    is_horizontal = w > h # 가로가 더 길면 -> 세로로 자름 (왼쪽에 Row 배치) -> layout 시 side는 h
    side = h if is_horizontal else w
    
    if side == 0: return []

    final_rects = []
    row = []
    children_copy = list(children) # Queue처럼 사용
    
    # 원래 인덱스와 값을 매핑하기 위해 (값, 원래인덱스) 튜플 사용 등을 고려해야 하지만
    # 여기서는 그냥 순서대로 반환하고 호출자가 매핑한다고 가정 (children이 정렬되어 들어옴)
    
    current_idx = 0
    row_area_sum = 0
    
    while current_idx < len(children_copy):
        c = children_copy[current_idx]
        
        # 현재 row에 c를 추가했을 때의 worst ratio
        row_with_c = row + [c]
        if worst_ratio(row, side) >= worst_ratio(row_with_c, side):
            # 비율이 좋아지거나 같으면 추가
            row.append(c)
            current_idx += 1
        else:
            # 비율이 나빠지면 현재 row 확정 및 배치
            row_area = sum(row)
            layout_rects = []
            
            if is_horizontal:
                # 캔버스가 가로로 긴 상태 -> 왼쪽에 세로 바(row)를 둠
                # side는 h
                row_width = row_area / h
                current_y = y
                for area in row:
                    rect_h = area / row_width
                    final_rects.append({'x': x, 'y': current_y, 'w': row_width, 'h': rect_h})
                    current_y += rect_h
                
                # 남은 영역 갱신
                x += row_width
                w -= row_width
            else:
                # 캔버스가 세로로 긴 상태 -> 위쪽에 가로 바(row)를 둠
                # side는 w
                row_height = row_area / w
                current_x = x
                for area in row:
                    rect_w = area / row_height
                    final_rects.append({'x': current_x, 'y': y, 'w': rect_w, 'h': row_height})
                    current_x += rect_w
                
                # 남은 영역 갱신
                y += row_height
                h -= row_height
            
            # 다음 row 준비
            row = []
            # 캔버스 형태가 바뀌었을 수 있으므로 is_horizontal 재계산
            is_horizontal = w > h
            side = h if is_horizontal else w
            if side <= 0: break # 더 이상 공간 없음

    # 남은 row 처리
    if row:
        row_area = sum(row)
        if is_horizontal:
            row_width = row_area / h if h > 0 else 0
            current_y = y
            for area in row:
                rect_h = area / row_width if row_width > 0 else 0
                final_rects.append({'x': x, 'y': current_y, 'w': row_width, 'h': rect_h})
                current_y += rect_h
        else:
            row_height = row_area / w if w > 0 else 0
            current_x = x
            for area in row:
                rect_w = area / row_height if row_height > 0 else 0
                final_rects.append({'x': current_x, 'y': y, 'w': rect_w, 'h': row_height})
                current_x += rect_w
                
    return final_rects

def calculate_treemap(data_list, x, y, width, height, value_key='weight'):
    """
    사용자 친화적 래퍼 함수
    data_list: [{'weight': 100, ...}, ...]
    반환: [{'x':, 'y':, 'w':, 'h':, 'data': original_item}, ...]
    """
    # 1. 값 추출 및 내림차순 정렬 (Squarified 필수 조건)
    # 인덱스를 기억하기 위해 enumerate 사용
    # [DETERMINISTIC] 무게가 같을 경우 티커/섹터 이름으로 정렬하여 배치 순서 고정
    indexed_data = list(enumerate(data_list))
    # ticker 또는 sector 키를 2차 정렬 기준으로 사용
    indexed_data.sort(key=lambda item: (
        item[1].get(value_key, 0), 
        item[1].get('ticker', item[1].get('sector', ''))
    ), reverse=True)
    
    values = [item[1].get(value_key, 0) for item in indexed_data]
    
    # 2. 아주 작은 값 필터링 (0 등)
    values = [v if v > 0 else 0.0001 for v in values] # 0 방지
    
    # 3. 정규화
    normalized_values = normalize_sizes(values, width, height)
    
    # 4. 좌표 계산
    rects = squarify(normalized_values, x, y, width, height)
    
    # 5. 데이터 매핑 복원
    result = []
    # rects 순서는 정렬된 values 순서와 같음
    for i, rect in enumerate(rects):
        original_index = indexed_data[i][0]
        original_item = indexed_data[i][1]
        
        # 정수 좌표로 변환 (UI 렌더링용)
        # [PRECISION] 정밀한 스마트 라운딩을 위해 소수점 좌표를 그대로 반환
        result.append({
            'x': rect['x'], 
            'y': rect['y'], 
            'w': rect['w'], 
            'h': rect['h'], 
            'data': original_item
        })
        
    return result
